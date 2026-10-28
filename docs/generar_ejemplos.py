"""Genera docs/ejemplos_respuesta.json con el CÓDIGO REAL de la API (fusión, validaciones, sobre homologado y
plan de atención) a partir de lecturas ficticias. Así los ejemplos de la documentación no se desfasan del código.

    python -m docs.generar_ejemplos
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import mrz_td1, plan, respuesta  # noqa: E402
from app.front_ocr import FrontOcr  # noqa: E402
from app.merge import Merger, needs_review  # noqa: E402
from app.schemas import Meta, ResultadoFM  # noqa: E402
from app.validators import curp_check_digit  # noqa: E402

SALIDA = Path(__file__).resolve().parent / "ejemplos_respuesta.json"


def _cd(s: str) -> str:
    return str(mrz_td1.check_digit(s))


def mrz_td1_lineas(numero: str, nac: str, sexo: str, exp: str | None, pais: str, apellidos: str, nombres: str) -> list[str]:
    """Arma una MRZ TD1 del INM con dígitos de control válidos (datos ficticios)."""
    l1 = f"I<MEX{numero}<{_cd(numero)}".ljust(30, "<")
    fecha_exp = f"{exp}{_cd(exp)}" if exp else "<<<<<<0"
    l2 = f"{nac}{_cd(nac)}{sexo}{fecha_exp}{pais}".ljust(29, "<")
    l2 += _cd(mrz_td1._composite(l1, l2 + "0"))
    l3 = (apellidos.replace(" ", "<") + "<<" + nombres.replace(" ", "<")).ljust(30, "<")[:30]
    return [l1, l2, l3]


def curp(c17: str) -> str:
    return c17 + curp_check_digit(c17)


CURP_OK = curp("PEGF900609MNERMR0")  # MARIA se salta: la inicial es la de FERNANDA
SOLICITUD = plan.Solicitud(nombre="Maria Fernanda Perez Gomez", curp=CURP_OK, fecha_nacimiento="1990-06-09",
                           nacionalidad="Colombiana")


def meta(**kw) -> Meta:
    base = dict(tiempo_total_ms=18400, tiempos_ms={"render": 310, "ocr_y_recorte": 6900, "vlm_anverso": 6200},
                modelo_vlm="qwen3-vl:8b-instruct", paginas=2, pagina_anverso=2, pagina_reverso=2,
                recorte_anverso="ancla", recorte_reverso="ancla", mrz_fuente="ocr", caracteres_leidos=812,
                categoria="forma_migratoria", otros_documentos=["pasaporte (COL)"],
                senales_fm=["INSTITUTO NACIONAL DE MIGRACIÓN", "RESIDENTE TEMPORAL", "NUE", "SEGOB-INM", "mrz_td1"])
    base.update(kw)
    return Meta(**base)


def procesar(vf: dict, vb: dict, of: FrontOcr, ob: FrontOcr, lineas: list[str], m: Meta,
             solicitud: plan.Solicitud = SOLICITUD) -> dict:
    mz = mrz_td1.parse(lineas)
    mg = Merger(vf, vb, of, ob, mz)
    d = mg.run()
    review = needs_review(mg.conf)
    r = ResultadoFM(estado="revisar" if review else "ok", datos=d, confianza=mg.conf, campos_a_revisar=review,
                    validaciones=mg.checks, advertencias=mg.warnings, meta=m)
    return respuesta.con_plan(respuesta.construir(r), solicitud)


def temporal(curp_impresa: str = CURP_OK, numero_reverso: str = "12345678") -> tuple:
    lineas = mrz_td1_lineas("12345678", "900609", "F", "250113", "COL", "PEREZ GOMEZ", "MARIA FERNANDA")
    vf = {"tipo_documento": "RESIDENTE TEMPORAL", "nue": "0000001234567", "nombre_completo": "PEREZ GOMEZ Maria Fernanda",
          "apellidos": "PEREZ GOMEZ", "nombres": "MARIA FERNANDA", "nacionalidad": "Colombiana", "pais": "COL",
          "sexo": "Mujer", "fecha_nacimiento": "09/06/1990", "curp": curp_impresa, "permiso_para_trabajar": True,
          "fecha_expedicion": "13/01/2025", "fecha_vencimiento": "12/01/2027"}
    vb = {"numero_segob_inm": "SEGOB-INM-00123456", "impreso_en": "OR CIUDAD DE MEXICO, 15/01/2025",
          "numero_documento": numero_reverso, "condicion_estancia": ""}
    of = FrontOcr(tipo_documento="RESIDENTE TEMPORAL", nue="0000001234567", curp=curp_impresa,
                  nombre_linea="PEREZ GOMEZ Maria Fernanda", permiso_para_trabajar=True, pais="COL",
                  fechas=["1990-06-09", "2025-01-13", "2027-01-12"])
    ob = FrontOcr(numero_segob_inm="SEGOB-INM-00123456", numero_documento=numero_reverso,
                  impreso_en="OR CIUDAD DE MEXICO, 15/01/2025")
    return vf, vb, of, ob, lineas


def main() -> None:
    ej: dict[str, dict] = {}
    ej["200"] = procesar(*temporal(), meta())

    curp_mala = curp("PEGF910609MNERMR0")  # la CURP impresa indica otro año: contradicción real
    ej["210"] = procesar(*temporal(curp_impresa=curp_mala), meta())

    ej["211"] = procesar(*temporal(numero_reverso="12345670"), meta())  # el reverso se leyó distinto que la MRZ

    lineas = mrz_td1_lineas("87654321", "850315", "M", None, "VEN", "RAMIREZ", "JOSE LUIS")
    vf = {"tipo_documento": "RESIDENTE PERMANENTE", "nue": "0000007654321", "nombre_completo": "RAMIREZ Jose Luis",
          "apellidos": "RAMIREZ", "nombres": "JOSE LUIS", "nacionalidad": "Venezolana", "pais": "VEN", "sexo": "Hombre",
          "fecha_nacimiento": "15/03/1985", "curp": "", "fecha_expedicion": "", "fecha_vencimiento": ""}
    vb = {"numero_segob_inm": "", "impreso_en": "", "numero_documento": "87654321", "condicion_estancia": ""}
    of = FrontOcr(tipo_documento="RESIDENTE PERMANENTE", nue="0000007654321", nombre_linea="RAMIREZ Jose Luis",
                  pais="VEN", fechas=["1985-03-15"])
    ob = FrontOcr(numero_documento="87654321",
                  impreso_en="EXPEDIDO EN: DELEGACION FEDERAL EN DISTRITO FEDERAL, 28/04/2015")
    ej["permanente"] = procesar(vf, vb, of, ob, lineas,
                         meta(paginas=1, pagina_anverso=1, pagina_reverso=1, otros_documentos=[],
                              senales_fm=["RESIDENTE PERMANENTE", "NUE", "mrz_td1"]))

    r220 = ResultadoFM(estado="rechazado", error="No se reconoció una tarjeta de residente del INM: sin MRZ válida, "
                                                 "sin NUE y sin título de la tarjeta (otros documentos: ine)",
                       meta=meta(paginas=1, pagina_anverso=None, pagina_reverso=None, categoria="otro",
                                 documento_detectado="ine", otros_documentos=["ine"], senales_fm=[],
                                 caracteres_leidos=607, tiempos_ms={"render": 250, "ocr_y_recorte": 5100}))
    ej["220"] = respuesta.con_plan(respuesta.construir(r220), SOLICITUD)
    r221 = ResultadoFM(estado="rechazado", error="El documento está en blanco o no tiene texto legible",
                       meta=meta(paginas=1, pagina_anverso=None, pagina_reverso=None, categoria="hoja_en_blanco",
                                 otros_documentos=[], senales_fm=[], caracteres_leidos=3,
                                 tiempos_ms={"render": 240, "ocr_y_recorte": 2100}))
    ej["221"] = respuesta.con_plan(respuesta.construir(r221), SOLICITUD)

    otra = plan.Solicitud(nombre="Maria Perez", curp=CURP_OK, fecha_nacimiento="1991-06-09", nacionalidad="Venezolana")
    ej["plan_rechazo"] = procesar(*temporal(), meta(), solicitud=otra)["validacion_plan"]
    ej["plan_sin_solicitud"] = procesar(*temporal(), meta(), solicitud=plan.Solicitud())["validacion_plan"]

    ej["400"] = respuesta.sobre(400, "expediente.jpg: tipo no soportado; se acepta PDF")
    ej["401"] = respuesta.sobre(401)
    ej["413"] = respuesta.sobre(413, "expediente.pdf: excede 25 MB")
    ej["422"] = respuesta.sobre(422, "La petición no es válida. file: Field required")
    ej["222"] = respuesta.sobre(222, "expediente.pdf: dice ser PDF pero su contenido es otra cosa")
    ej["223"] = respuesta.sobre(223)
    ej["224"] = respuesta.sobre(224)
    ej["500"] = respuesta.sobre(500)
    ej["502"] = respuesta.sobre(502, respuesta.MENSAJES[502] + " Detalle: El VLM no respondió correctamente")

    for c in ("200", "210", "211"):
        assert ej[c]["codigo"] == int(c), (c, ej[c]["codigo"], ej[c].get("validacion"), ej[c].get("avisos"))
    SALIDA.write_text(json.dumps(ej, ensure_ascii=False, indent=2), encoding="utf-8")
    print("ok", SALIDA)


if __name__ == "__main__":
    main()
