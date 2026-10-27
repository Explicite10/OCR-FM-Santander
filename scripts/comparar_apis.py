"""Corre DOS APIs de forma migratoria (p. ej. Open Source y Document AI) sobre la misma carpeta de PDFs
y compara las respuestas homologadas campo por campo.

    API_A_URL=http://localhost:18475 API_A_KEY=... API_B_URL=http://localhost:18476 API_B_KEY=... \\
    python -m scripts.comparar_apis lote/pdfs --salida lote/comparacion --concurrencia 2 [--limite 50]

Reanudable: guarda cada respuesta en <salida>/json/<api>/<archivo>.json y no vuelve a pedirla.
Genera:
- comparacion.csv: valor de cada campo en A y B por documento (DATOS PERSONALES: no sacar del servidor)
- comparacion.md: resumen SIN datos personales (códigos, acuerdo por campo, quién acierta contra la MRZ,
  tiempos y la lista de archivos con diferencias por campo) para analizar mejoras.

Árbitro: cuando A y B difieren en un campo que la MRZ respalda con dígito verificador (número de documento,
fecha de nacimiento, sexo, fecha de expedición, nacionalidad, apellidos/nombres) se toma la MRZ íntegra como
verdad; la CURP se arbitra con su dígito verificador. Lo demás sólo se reporta como "difieren".
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import statistics
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import validators as v  # noqa: E402

EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
CAMPOS = ["tipo_documento", "nue", "apellidos", "nombres", "nacionalidad", "pais", "sexo", "fecha_nacimiento",
          "curp", "permiso_para_trabajar", "fecha_expedicion", "fecha_vencimiento", "vigente", "numero_documento",
          "numero_segob_inm", "impreso_en"]
# campo de datos -> campo de la MRZ que lo respalda (y el dígito de control que debe cuadrar)
MRZ_ARBITRA = {"numero_documento": ("numero_documento", "numero_documento"),
               "fecha_nacimiento": ("fecha_nacimiento", "fecha_nacimiento"),
               "fecha_expedicion": ("fecha_expedicion", "fecha_expedicion"),
               "sexo": ("sexo", "fecha_nacimiento"), "pais": ("nacionalidad", "compuesto"),
               "apellidos": ("apellidos", "compuesto"), "nombres": ("nombres", "compuesto")}
SEXO = {"H": "H", "M": "M", "F": "M", "X": "X"}


def _norm(s) -> str:
    if s is None or s is False:
        return ""
    s = str(s)
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def normaliza(campo: str, val) -> str:
    """Valor comparable: sin acentos, mayúsculas, sin ceros a la izquierda en números, sexo H/M, etc."""
    if val in (None, "", [], {}):
        return ""
    if campo == "permiso_para_trabajar":
        return "SI" if val is True else ""
    if campo == "vigente":
        return "SI" if val is True else "NO" if val is False else ""
    n = _norm(val)
    if campo in ("numero_documento", "nue"):
        return n.lstrip("0") or "0"
    if campo == "sexo":
        return SEXO.get(n, n)
    if campo == "numero_segob_inm":
        return re.sub(r"\D", "", n)
    if campo == "impreso_en":
        return re.sub(r"\d{8}$", "", _norm(re.split(r",", str(val))[0]))  # oficina sin la fecha
    if campo == "nacionalidad":
        return v.nationality_iso(str(val)) or n
    return n


def mrz_verdad(body: dict, campo: str) -> str | None:
    """Valor del campo según la MRZ si su dígito de control cuadra; None si no hay respaldo."""
    mrz = body.get("mrz") or {}
    if "error" in mrz or campo not in MRZ_ARBITRA:
        return None
    k, dc = MRZ_ARBITRA[campo]
    if not (mrz.get("digitos_control") or {}).get(dc):
        return None
    val = mrz.get(k)
    if not val:
        return None
    if campo in ("apellidos", "nombres"):
        return _norm(val)
    return normaliza(campo, val)


def nombres_compatibles(a: str, b: str) -> bool:
    """La MRZ trunca nombres a 30 caracteres: se acepta prefijo."""
    return bool(a) and bool(b) and (a == b or a.startswith(b) or b.startswith(a))


async def pedir(client: httpx.AsyncClient, url: str, key: str, path: Path) -> dict:
    with open(path, "rb") as f:
        files = {"file": (path.name, f, "application/pdf" if path.suffix.lower() == ".pdf" else "image/jpeg")}
        r = await client.post(f"{url.rstrip('/')}/forma-migratoria", headers={"X-API-Key": key}, files=files)
    try:
        return r.json()
    except ValueError:
        return {"codigo": r.status_code, "estado": "RESPUESTA_NO_JSON", "mensaje": r.text[:200]}


async def correr(nombre: str, url: str, key: str, archivos: list[Path], out: Path, conc: int, timeout: float) -> None:
    out.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(conc)
    pendientes = [p for p in archivos if not (out / f"{p.name}.json").exists()]
    print(f"[{nombre}] {len(archivos)} archivos, {len(pendientes)} por pedir a {url}")
    hechos = 0

    async with httpx.AsyncClient(timeout=timeout) as client:
        async def uno(p: Path) -> None:
            nonlocal hechos
            async with sem:
                try:
                    body = await pedir(client, url, key, p)
                except Exception as e:  # noqa: BLE001
                    body = {"codigo": 0, "estado": "SIN_RESPUESTA", "mensaje": str(e)[:200]}
                (out / f"{p.name}.json").write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
                hechos += 1
                if hechos % 20 == 0:
                    print(f"[{nombre}] {hechos}/{len(pendientes)}")

        await asyncio.gather(*(uno(p) for p in pendientes))


def cargar(out: Path, archivos: list[Path]) -> dict[str, dict]:
    res = {}
    for p in archivos:
        f = out / f"{p.name}.json"
        if f.exists():
            res[p.name] = json.loads(f.read_text(encoding="utf-8"))
    return res


def comparar(a: dict[str, dict], b: dict[str, dict], na: str, nb: str, salida: Path) -> None:
    comunes = sorted(set(a) & set(b))
    filas = []
    acuerdo: dict[str, Counter] = defaultdict(Counter)   # campo -> {igual, solo_a, solo_b, difieren, vacios}
    arbitro: dict[str, Counter] = defaultdict(Counter)   # campo -> {a_acierta, b_acierta, ninguno, sin_arbitro}
    difs: dict[str, list[str]] = defaultdict(list)
    plan: Counter = Counter()

    for k in comunes:
        ra, rb = a[k], b[k]
        da, db = ra.get("datos") or {}, rb.get("datos") or {}
        fila = {"archivo": k, f"codigo_{na}": ra.get("codigo"), f"codigo_{nb}": rb.get("codigo"),
                f"ms_{na}": (ra.get("meta") or {}).get("tiempo_total_ms"),
                f"ms_{nb}": (rb.get("meta") or {}).get("tiempo_total_ms")}
        pa, pb = (ra.get("validacion_plan") or {}).get("cumple"), (rb.get("validacion_plan") or {}).get("cumple")
        plan[f"{na}={pa} {nb}={pb}"] += 1
        for c in CAMPOS:
            xa, xb = normaliza(c, da.get(c)), normaliza(c, db.get(c))
            fila[f"{c}_{na}"], fila[f"{c}_{nb}"] = da.get(c), db.get(c)
            if not xa and not xb:
                acuerdo[c]["vacios"] += 1
                continue
            if xa == xb or (c in ("apellidos", "nombres", "impreso_en") and nombres_compatibles(xa, xb)):
                acuerdo[c]["igual"] += 1
                continue
            acuerdo[c]["solo_" + na if xa and not xb else "solo_" + nb if xb and not xa else "difieren"] += 1
            difs[c].append(k)
            # árbitro
            verdad = None
            if c == "curp":
                va, vb = v.curp_valid(da.get(c)), v.curp_valid(db.get(c))
                if va != vb:
                    verdad = xa if va else xb
            else:
                verdad = mrz_verdad(ra, c) or mrz_verdad(rb, c)
            if verdad is None:
                arbitro[c]["sin_arbitro"] += 1
            else:
                ok_a = nombres_compatibles(xa, verdad) if c in ("apellidos", "nombres") else xa == verdad
                ok_b = nombres_compatibles(xb, verdad) if c in ("apellidos", "nombres") else xb == verdad
                arbitro[c][f"{na}_acierta" if ok_a and not ok_b else f"{nb}_acierta" if ok_b and not ok_a
                           else "ambos" if ok_a and ok_b else "ninguno"] += 1
                fila[f"{c}_arbitro"] = na if ok_a and not ok_b else nb if ok_b and not ok_a else "-"
        filas.append(fila)

    salida.mkdir(parents=True, exist_ok=True)
    cols = list(dict.fromkeys(c for f in filas for c in f))
    with open(salida / "comparacion.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(filas)

    md = [f"# Comparación {na} vs {nb} ({len(comunes)} documentos)\n"]
    for nombre, run in ((na, a), (nb, b)):
        cod = Counter(run[k].get("codigo") for k in comunes)
        ms = [run[k]["meta"]["tiempo_total_ms"] / 1000 for k in comunes if (run[k].get("meta") or {}).get("tiempo_total_ms")]
        med = f"mediana {statistics.median(ms):.1f} s, p90 {sorted(ms)[int(len(ms) * 0.9) - 1]:.1f} s" if ms else "-"
        md.append(f"- **{nombre}**: códigos {dict(sorted(cod.items(), key=lambda x: str(x[0])))} · tiempo {med}")
    md.append("")
    md.append("## Plan de atención (`validacion_plan.cumple`, sin datos de solicitud)\n")
    md += [f"- {k}: {n}" for k, n in plan.most_common()]
    md.append("")
    md.append("## Acuerdo por campo\n")
    md.append(f"| Campo | igual | sólo {na} | sólo {nb} | difieren | ambos vacíos | árbitro: {na} acierta | {nb} acierta | ambos | ninguno | sin árbitro |")
    md.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for c in CAMPOS:
        ac, ar = acuerdo[c], arbitro[c]
        md.append(f"| {c} | {ac['igual']} | {ac['solo_' + na]} | {ac['solo_' + nb]} | {ac['difieren']} | {ac['vacios']} | "
                  f"{ar[na + '_acierta']} | {ar[nb + '_acierta']} | {ar['ambos']} | {ar['ninguno']} | {ar['sin_arbitro']} |")
    md.append("")
    md.append("## Archivos con diferencias por campo (para revisar a mano)\n")
    for c in CAMPOS:
        if difs[c]:
            md.append(f"- **{c}** ({len(difs[c])}): {', '.join(difs[c][:40])}{' ...' if len(difs[c]) > 40 else ''}")
    md.append("")
    md.append("Lectura: 'sólo X' = X extrajo el dato y el otro no. 'árbitro' sólo se calcula cuando difieren y la MRZ "
              "íntegra (o el dígito verificador de la CURP) dice quién tiene razón.")
    (salida / "comparacion.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdfs", type=Path)
    ap.add_argument("--salida", type=Path, default=Path("lote/comparacion"))
    ap.add_argument("--concurrencia", type=int, default=2)
    ap.add_argument("--limite", type=int, default=0, help="sólo los primeros N archivos (0 = todos)")
    ap.add_argument("--nombre-a", default=os.environ.get("API_A_NOMBRE", "opensource"))
    ap.add_argument("--nombre-b", default=os.environ.get("API_B_NOMBRE", "documentai"))
    ap.add_argument("--timeout", type=float, default=300)
    ap.add_argument("--solo-resumen", action="store_true")
    args = ap.parse_args()

    archivos = sorted(p for p in args.pdfs.iterdir() if p.suffix.lower() in EXTS)
    if args.limite:
        archivos = archivos[: args.limite]
    if not archivos:
        raise SystemExit("No hay archivos")
    out_a, out_b = args.salida / "json" / args.nombre_a, args.salida / "json" / args.nombre_b
    if not args.solo_resumen:
        ua, ub = os.environ.get("API_A_URL"), os.environ.get("API_B_URL")
        if not ua or not ub:
            raise SystemExit("Define API_A_URL/API_A_KEY y API_B_URL/API_B_KEY")

        async def ambas() -> None:
            await asyncio.gather(
                correr(args.nombre_a, ua, os.environ.get("API_A_KEY", ""), archivos, out_a, args.concurrencia, args.timeout),
                correr(args.nombre_b, ub, os.environ.get("API_B_KEY", ""), archivos, out_b, args.concurrencia, args.timeout))

        asyncio.run(ambas())
    comparar(cargar(out_a, archivos), cargar(out_b, archivos), args.nombre_a, args.nombre_b, args.salida)


if __name__ == "__main__":
    main()
