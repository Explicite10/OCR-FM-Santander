"""Procesa una carpeta de PDFs con tarjetas de residente del INM y genera JSON, CSV y un resumen.

    python -m scripts.procesar_lote lote/pdfs --salida lote/resultados --concurrencia 3 --recortes
    python -m scripts.procesar_lote --salida lote/resultados --solo-resumen

Reanudable: salta los archivos que ya tienen JSON (--forzar para reprocesar). Genera:
- json/*.json y resultados.csv: datos completos (personales; no sacar del servidor)
- diagnostico.csv y resumen.md: sin datos personales (para analizar mejoras)
"""

import argparse
import asyncio
import base64
import csv
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import pipeline, respuesta  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.ocr import engine  # noqa: E402
from app.schemas import ResultadoFM  # noqa: E402
from app.vlm import VlmClient  # noqa: E402

EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp"}
CONF_FIELDS = ["tipo_documento", "nue", "nombre", "nacionalidad", "pais", "sexo", "fecha_nacimiento", "curp",
               "fecha_expedicion", "fecha_vencimiento", "numero_documento", "numero_segob_inm"]
MRZ_RULES = ("mrz_numero", "mrz_fecha_nacimiento", "mrz_fecha_expedicion", "mrz_compuesto")


def codigo_api(r: dict) -> int | None:
    try:
        return respuesta.construir(ResultadoFM.model_validate(r))["codigo"]
    except Exception:  # noqa: BLE001
        return None


def flatten(r: dict) -> dict:
    d = r.get("datos") or {}
    n = d.get("nombre") or {}
    conf = r.get("confianza") or {}
    checks = {c["regla"]: c["resultado"] for c in r.get("validaciones") or []}
    mrz_ok = all(checks.get(k) == "ok" for k in MRZ_RULES if k in checks) and "mrz_numero" in checks
    row = {"archivo": r.get("archivo"), "estado": r.get("estado"), "codigo_api": codigo_api(r),
           "campos_a_revisar": ";".join(r.get("campos_a_revisar") or [])}
    for k in ("tipo_documento", "nue"):
        row[k] = d.get(k)
    row.update({"apellidos": n.get("apellidos"), "nombres": n.get("nombres"), "nombre_completo": n.get("nombre_completo")})
    for k in ("nacionalidad", "pais", "sexo", "fecha_nacimiento", "curp", "permiso_para_trabajar", "fecha_expedicion",
              "fecha_vencimiento", "vigente", "numero_documento", "numero_segob_inm", "impreso_en", "mrz_nacionalidad"):
        row[k] = d.get(k)
    row["mrz_valida"] = mrz_ok
    row["tiempo_ms"] = (r.get("meta") or {}).get("tiempo_total_ms")
    row["advertencias"] = " | ".join(r.get("advertencias") or [])
    row["error"] = r.get("error")
    for f in CONF_FIELDS:
        row[f"conf_{f}"] = conf.get(f)
    return row


def diagnose(r: dict) -> dict:
    meta = r.get("meta") or {}
    conf = r.get("confianza") or {}
    d = r.get("datos") or {}
    row = {
        "archivo": r.get("archivo"), "estado": r.get("estado"), "codigo_api": codigo_api(r),
        "tipo_documento": d.get("tipo_documento"), "pais": d.get("pais"),
        "campos_a_revisar": ";".join(r.get("campos_a_revisar") or []),
        "validaciones_falla": ";".join(c["regla"] for c in r.get("validaciones") or [] if c["resultado"] == "falla"),
        "advertencias": ";".join(a.split("(")[0].strip() for a in r.get("advertencias") or []),
        "motivo_rechazo": (r.get("error") or None) if r.get("estado") == "rechazado" else None,
        "error_tipo": (r.get("error") or "").split(":")[0] or None,
        "senales_fm": ";".join(meta.get("senales_fm") or []),
        "otros_documentos": ";".join(meta.get("otros_documentos") or []),
        "paginas": meta.get("paginas"), "rotado": meta.get("rotado"),
        "pagina_anverso": meta.get("pagina_anverso"), "pagina_reverso": meta.get("pagina_reverso"),
        "recorte_anverso": meta.get("recorte_anverso"), "recorte_reverso": meta.get("recorte_reverso"),
        "mrz_fuente": meta.get("mrz_fuente"), "tiempo_total_ms": meta.get("tiempo_total_ms"),
    }
    for etapa, ms in (meta.get("tiempos_ms") or {}).items():
        row[f"ms_{etapa}"] = ms
    for f in CONF_FIELDS:
        row[f"conf_{f}"] = conf.get(f)
    return row


def write_reports(out: Path) -> None:
    results = []
    for p in sorted((out / "json").glob("*.json")):
        try:
            results.append(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            print(f"JSON corrupto, se omite: {p}")
    if not results:
        print("No hay resultados todavía.")
        return
    rows = [flatten(r) for r in results]
    with open(out / "resultados.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    diag = [diagnose(r) for r in results]
    fields = list(dict.fromkeys(k for d in diag for k in d))
    with open(out / "diagnostico.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(diag)

    total = len(rows)
    states = Counter(r["estado"] for r in rows)
    pct = lambda n: f"{100 * n / total:.1f}%"  # noqa: E731
    times = [r["tiempo_ms"] / 1000 for r in rows if r["tiempo_ms"]]
    checks = Counter(c["regla"] for r in results for c in r.get("validaciones") or [] if c["resultado"] == "falla")
    review = Counter(f for r in rows for f in (r["campos_a_revisar"] or "").split(";") if f)
    lines = [
        f"# Resumen del lote ({total} documentos) · VLM: {get_settings().vlm_model}", "",
        f"- ok: {states['ok']} ({pct(states['ok'])}) · revisar: {states['revisar']} ({pct(states['revisar'])}) · "
        f"rechazado: {states['rechazado']} ({pct(states['rechazado'])}) · error: {states['error']}",
        f"- MRZ íntegra (dígitos verificadores): {sum(r['mrz_valida'] for r in rows)} ({pct(sum(r['mrz_valida'] for r in rows))})",
        f"- mrz_fuente: {dict(Counter(d['mrz_fuente'] for d in diag))} · recorte reverso: {dict(Counter(d['recorte_reverso'] for d in diag))} · "
        f"recorte anverso: {dict(Counter(d['recorte_anverso'] for d in diag))}",
        f"- tipo: {dict(Counter(r['tipo_documento'] for r in rows))}",
    ]
    if times:
        lines.append(f"- tiempo por documento: mediana {statistics.median(times):.1f} s, p90 "
                     f"{sorted(times)[int(0.9 * (len(times) - 1))]:.1f} s, total {sum(times) / 60:.1f} min")
    stages: dict[str, list[float]] = {}
    for r in results:
        for etapa, ms in ((r.get("meta") or {}).get("tiempos_ms") or {}).items():
            stages.setdefault(etapa, []).append(ms / 1000)
    if stages:
        lines.append("- mediana por etapa: " + ", ".join(f"{k} {statistics.median(v):.1f} s" for k, v in stages.items()))
    codigos = Counter(r["codigo_api"] for r in rows)
    lines += ["", "## Código de la API", "", "| codigo | estado | docs |", "|---:|---|---|"]
    lines += [f"| {c} | {respuesta.ESTADOS.get(c, '?') if c else '-'} | {n} ({pct(n)}) |"
              for c, n in sorted(codigos.items(), key=lambda x: (x[0] is None, x[0] or 0))]
    disc = Counter()
    for r in results:
        try:
            body = respuesta.construir(ResultadoFM.model_validate(r))
        except Exception:  # noqa: BLE001
            continue
        for d in (body.get("validacion") or {}).get("discrepancias") or []:
            disc[d.split(":")[0]] += 1
    if disc:
        lines += ["", "## Discrepancias que reportaría la API", "", "| Comprobación | docs |", "|---|---|"]
        lines += [f"| {k} | {v} ({pct(v)}) |" for k, v in disc.most_common()]
    lines += ["", "## Confianza por campo (alta / media / baja / sin dato)", "", "| Campo | alta | media | baja | vacío |", "|---|---|---|---|---|"]
    for f in CONF_FIELDS:
        c = Counter(r[f"conf_{f}"] for r in rows)
        lines.append(f"| {f} | {c['alta']} | {c['media']} | {c['baja']} | {c[None]} |")
    lines += ["", "## Validaciones que más fallan", "", "| Regla | docs |", "|---|---|"]
    lines += [f"| {k} | {v} ({pct(v)}) |" for k, v in checks.most_common(20)]
    lines += ["", "## Campos enviados a revisión", "", "| Campo | docs |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in review.most_common()]
    rech = [(r["archivo"], r["error"]) for r in rows if r["estado"] in ("rechazado", "error")]
    if rech:
        lines += ["", "## Rechazos y errores", ""] + [f"- {a}: {e}" for a, e in rech]
    (out / "resumen.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:8]))


async def run(files: list[Path], out: Path, concurrency: int, save_crops: bool) -> None:
    s = get_settings()
    vlm = VlmClient(s) if s.vlm_enabled else None
    if vlm and not await vlm.health():
        print(f"ERROR: el modelo {s.vlm_model} no responde en {s.vlm_base_url}")
        sys.exit(1)
    print("Cargando PaddleOCR...")
    await asyncio.to_thread(engine.warmup)
    sem = asyncio.Semaphore(concurrency)
    done = 0
    t0 = time.perf_counter()

    async def one(path: Path) -> None:
        nonlocal done
        async with sem:
            try:
                result = await pipeline.process([path.read_bytes()], vlm, path.name, include_crops=save_crops)
                data = result.model_dump(mode="json")
            except Exception as e:  # noqa: BLE001
                data = {"archivo": path.name, "estado": "error", "error": f"{type(e).__name__}: {e}"}
            crops = data.pop("recortes", None) or {}
            for side, b64 in crops.items():
                (out / "recortes" / f"{path.stem}_{side}.png").write_bytes(base64.b64decode(b64))
            tmp = out / "json" / f"{path.stem}.json.tmp"
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(out / "json" / f"{path.stem}.json")
            done += 1
            elapsed = time.perf_counter() - t0
            eta = elapsed / done * (len(files) - done)
            revisar = ",".join(data.get("campos_a_revisar") or [])
            print(f"[{done}/{len(files)}] {path.name}: {data['estado']}{' (' + revisar + ')' if revisar else ''}  "
                  f"ETA {eta / 60:.1f} min", flush=True)

    await asyncio.gather(*(one(f) for f in files))
    if vlm:
        await vlm.aclose()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("entrada", nargs="?", type=Path)
    ap.add_argument("--salida", type=Path, default=Path("resultados"))
    ap.add_argument("--concurrencia", type=int, default=2)
    ap.add_argument("--limite", type=int, default=None)
    ap.add_argument("--forzar", action="store_true")
    ap.add_argument("--recortes", action="store_true")
    ap.add_argument("--solo-resumen", action="store_true")
    args = ap.parse_args()
    out: Path = args.salida
    (out / "json").mkdir(parents=True, exist_ok=True)
    (out / "recortes").mkdir(exist_ok=True)
    if not args.solo_resumen:
        if not args.entrada or not args.entrada.is_dir():
            ap.error("indica la carpeta de entrada")
        files = sorted(p for p in args.entrada.rglob("*") if p.suffix.lower() in EXTS)
        pending = [p for p in files if args.forzar or not (out / "json" / f"{p.stem}.json").exists()]
        if args.limite:
            pending = pending[: args.limite]
        print(f"{len(files)} archivos encontrados, {len(pending)} por procesar")
        if pending:
            asyncio.run(run(pending, out, args.concurrencia, args.recortes))
    write_reports(out)


if __name__ == "__main__":
    main()
