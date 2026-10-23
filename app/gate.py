"""Señales de que el PDF trae una tarjeta de residente del INM.

A diferencia de la API de INE, aquí el mismo PDF casi siempre trae OTROS documentos (pasaporte,
licencia, INE), así que su texto no sirve para rechazar: sólo se reporta en `meta.otros_documentos`.
Se rechaza (código 220) únicamente cuando, después del OCR y del modelo de visión, no aparece
ninguna señal de tarjeta INM ni datos válidos de ella (MRZ con dígitos verificadores, NUE, CURP de
extranjero).
"""

import re
from dataclasses import dataclass, field

from .layout import _n, is_header, is_title
from .ocr import Line

EXCLUSIVE = {
    "SEGOBINM": "SEGOB-INM",
    "NUMEROUNICODEEXTRANJERO": "NUE",
    "PERMISOPARATRABAJAR": "PERMISO PARA TRABAJAR",
    "CONDICIONDEESTANCIA": "CONDICIÓN DE ESTANCIA",
    "TARJETADERESIDENTE": "TARJETA DE RESIDENTE",
}
GENERIC = {
    "NACIONALIDAD": "NACIONALIDAD",
    "CURP": "CURP",
    "FECHADENACIMIENTO": "FECHA DE NACIMIENTO",
    "SECRETARIADEGOBERNACION": "SECRETARÍA DE GOBERNACIÓN",
    "ESTADOSUNIDOSMEXICANOS": "ESTADOS UNIDOS MEXICANOS",
    "FECHADEEXPEDICION": "FECHA DE EXPEDICIÓN",
    "FECHADEVENCIMIENTO": "FECHA DE VENCIMIENTO",
}


@dataclass
class Veredicto:
    es_fm: bool
    puntaje: int
    senales: list[str] = field(default_factory=list)
    motivo: str | None = None


def evaluate(page_lines: list[list[Line]], front_ancla: bool, mrz_td1: bool) -> Veredicto:
    exclusive: set[str] = set()
    generic: set[str] = set()
    if front_ancla:
        exclusive.add("anverso")
    if mrz_td1:
        exclusive.add("mrz_td1")
    for lines in page_lines:
        for l in lines:
            t = _n(l.text)
            if is_header(t):
                exclusive.add("INSTITUTO NACIONAL DE MIGRACIÓN")
            tipo = is_title(t)
            if tipo:
                exclusive.add(tipo)
            if re.fullmatch(r"NUE:?", t) or re.match(r"^NUE:?\d{13}$", t):
                exclusive.add("NUE")
            for key, label in EXCLUSIVE.items():
                if key in t:
                    exclusive.add(label)
            for key, label in GENERIC.items():
                if t == key or (len(key) >= 8 and key in t):
                    generic.add(label)
    senales = sorted(exclusive) + sorted(generic)
    puntaje = 3 * len(exclusive) + len(generic)
    if not exclusive:
        return Veredicto(False, puntaje, senales,
                         "No se reconoció una tarjeta de residente del INM: sin encabezado, título, NUE ni MRZ I<MEX")
    return Veredicto(True, puntaje, senales)
