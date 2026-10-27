"""Extrae campos de la tarjeta a partir de las líneas de PaddleOCR (segunda opinión del VLM)."""

import re
from dataclasses import dataclass, field

from .layout import is_title
from .ocr import Line
from .validators import CURP_RE, SEGOB_RE, normalize_curp, parse_date, strip_accents


@dataclass
class FrontOcr:
    tipo_documento: str | None = None
    nue: str | None = None
    curp: str | None = None
    fechas: list[str] = field(default_factory=list)  # ISO, en orden de aparición
    nombre_linea: str | None = None
    permiso_para_trabajar: bool = False
    pais: str | None = None
    numero_segob_inm: str | None = None
    numero_documento: str | None = None
    impreso_en: str | None = None


def _n(t: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", strip_accents(t.upper()))


def _find_curp(texts: list[str]) -> str | None:
    for t in texts:
        compact = _n(t).replace("CURP", "")
        for i in range(0, max(1, len(compact) - 17)):
            cand = normalize_curp(compact[i:i + 18])
            if cand and len(cand) == 18 and CURP_RE.match(cand):
                return cand
    return None


def extract(lines: list[Line]) -> FrontOcr:
    res = FrontOcr()
    if not lines:
        return res
    texts = [l.text for l in lines]
    for i, l in enumerate(lines):
        n = _n(l.text)
        t = is_title(l.text)
        if t and res.tipo_documento is None:
            res.tipo_documento = t
        m = re.search(r"NUE[:\s]*(\d{13})", n) or re.fullmatch(r"(\d{13})", n)
        if m and res.nue is None:
            res.nue = m.group(1)
        if "PERMISOPARATRABAJAR" in n:
            res.permiso_para_trabajar = True
        m = re.search(r"(SEGOB-?INM-?\d{6,10})", strip_accents(l.text.upper()).replace(" ", ""))
        if m and res.numero_segob_inm is None:
            seg = "SEGOB-INM-" + re.sub(r"\D", "", m.group(1))
            if SEGOB_RE.match(seg):
                res.numero_segob_inm = seg
        m = re.search(r"IMPRESO\s*EN\s*:?\s*(.+)$", strip_accents(l.text.upper()))
        if m and res.impreso_en is None:
            rest = m.group(1).strip(" :-")
            if len(rest) < 4 and i + 1 < len(lines):  # "Impreso en:" solo y el valor en la línea siguiente
                rest = strip_accents(lines[i + 1].text.upper()).strip()
            if len(rest) >= 4:
                res.impreso_en = re.sub(r"\s+", " ", rest)
        m = re.fullmatch(r"NO\.?(\d{7,9})", n)
        if m and res.numero_documento is None:
            res.numero_documento = m.group(1)
        if re.fullmatch(r"PAIS(COUNTRY)?[:]?([A-Z]{3})", n):
            res.pais = n[-3:]
        if n.startswith("NOMBRE") and res.nombre_linea is None:
            rest = re.sub(r"^\s*NOMBRE\s*/?\s*NAME\s*:?", "", strip_accents(l.text.upper())).strip()
            if len(rest) >= 4:
                res.nombre_linea = rest
            elif i + 1 < len(lines):
                res.nombre_linea = lines[i + 1].text.strip()
    res.curp = _find_curp([t for t in texts if "CURP" in _n(t)] + texts)
    for t in texts:
        for m in re.finditer(r"\d{1,2}\s*[/\-.]\s*\d{1,2}\s*[/\-.]\s*\d{4}", t):
            d = parse_date(m.group(0))
            if d and 1900 < d.year < 2100:
                res.fechas.append(d.isoformat())
    return res
