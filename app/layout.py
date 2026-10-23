"""Localiza anverso y reverso de la tarjeta de residente del INM dentro de cada página.

Se usan anclas en el texto del OCR (los sellos del banco y los marcos de las fotocopias
confunden a un detector de rectángulos):

* Reverso: las 3 líneas MRZ TD1 ("I<MEX...").
* Anverso: el título "RESIDENTE TEMPORAL" / "RESIDENTE PERMANENTE" (o "INMIGRADO" en las FM2
  antiguas); si no se lee, el encabezado "INSTITUTO NACIONAL DE MIGRACIÓN" + etiquetas.

Con la posición y el ancho del ancla se estima el rectángulo de la tarjeta (proporciones medidas
sobre tarjetas reales) y se agrega un margen. Si en ninguna página aparece un ancla, el pipeline
pide al modelo de visión que ubique las tarjetas y `analyze_boxes` repite la búsqueda ahí.

El mismo PDF suele traer además pasaporte, licencia o INE: se detectan (para `meta.otros_documentos`)
pero no se recortan.
"""

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import cv2
import numpy as np

from .mrz_td1 import find_mrz_lines
from .ocr import Line
from .validators import strip_accents

CARD_RATIO = 85.6 / 54.0
MARGIN = 0.08

# Anverso, a partir del título "RESIDENTE TEMPORAL/PERMANENTE" (medido en tarjetas reales)
TITLE_W_PER_CARD = 0.31  # ancho del título / ancho de tarjeta
TITLE_LEFT_OFFSET = 0.29  # fracción del ancho de tarjeta a la izquierda del título
TITLE_TOP_OFFSET = 0.17  # fracción del alto de tarjeta por encima del título
# Anverso, a partir del encabezado "INSTITUTO NACIONAL DE MIGRACION" (arriba a la derecha)
HEADER_W_PER_CARD = 0.38
HEADER_LEFT_OFFSET = 0.54
HEADER_TOP_OFFSET = 0.05
# Reverso, a partir de la MRZ (abajo, casi del ancho de la tarjeta)
BACK_W_PER_MRZ = 1.10
BACK_LEFT_OFFSET = 0.04
BACK_BOTTOM_OFFSET = 0.07

CROP_MIN_WIDTH = 1100
_ROTATIONS = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}


@dataclass
class Box:
    x0: int
    y0: int
    x1: int
    y1: int

    def contains(self, x: float, y: float) -> bool:
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1

    def clip(self, w: int, h: int) -> "Box":
        return Box(max(0, self.x0), max(0, self.y0), min(w, self.x1), min(h, self.y1))

    @property
    def area(self) -> int:
        return max(0, self.x1 - self.x0) * max(0, self.y1 - self.y0)


@dataclass
class Side:
    page: int
    box: Box
    image: np.ndarray
    lines: list[Line]
    method: str  # "ancla" | "localizador" | "pagina_completa"
    mrz_lines: list[str] = field(default_factory=list)


@dataclass
class Layout:
    front: Side | None
    back: Side | None
    rotated: bool
    pages: int
    warnings: list[str]
    page_lines: list[list[Line]] = field(default_factory=list)
    page_images: list[np.ndarray] = field(default_factory=list)
    otros_documentos: list[str] = field(default_factory=list)

    @property
    def anchored(self) -> bool:
        return bool(self.front and self.front.method == "ancla" and self.back and self.back.method == "ancla")


def _n(t: str) -> str:
    return re.sub(r"[^A-Z0-9<]", "", strip_accents(t.upper()))


def _fuzzy_in(text: str, target: str, threshold: float = 0.75) -> bool:
    t = _n(text)
    if target in t:
        return True
    if len(t) < len(target) * 0.6:
        return False
    return SequenceMatcher(None, t[: len(target) + 4], target).ratio() >= threshold


def is_title(t: str) -> str | None:
    """Devuelve el tipo de tarjeta si la línea es su título."""
    n = _n(t)
    if _fuzzy_in(n, "RESIDENTETEMPORAL"):
        return "RESIDENTE TEMPORAL"
    if _fuzzy_in(n, "RESIDENTEPERMANENTE"):
        return "RESIDENTE PERMANENTE"
    if n.startswith("INMIGRADO") or n == "INMIGRANTE" or n.startswith("NOINMIGRANTE"):
        return n if n in ("INMIGRADO", "INMIGRANTE", "NOINMIGRANTE") else "INMIGRADO"
    if _fuzzy_in(n, "VISITANTE") and len(n) < 40:
        return "VISITANTE"
    return None


def is_header(t: str) -> bool:
    return _fuzzy_in(t, "INSTITUTONACIONALDEMIGRACION")


_PASSPORT_MRZ = re.compile(r"^P[A-Z<][A-Z]{3}[A-Z0-9<]{15,}$")
_INE_MRZ = re.compile(r"^[1IL]?D[MN]EX\d{5}")


def _x_overlap(a: Line, b: Line) -> float:
    inter = min(a.x1, b.x1) - max(a.x0, b.x0)
    return inter / max(1, min(a.w, b.w))


def find_mrz(lines: list[Line]) -> list[Line] | None:
    """Las líneas MRZ TD1 (2 ó 3) agrupadas geométricamente."""
    texts = [l.text for l in lines]
    found = find_mrz_lines(texts)
    if not found:
        return None
    if found[0]:
        l1 = lines[texts.index(found[0])]
        below = [
            l for l in lines
            if l is not l1 and l.cy > l1.cy + 0.4 * l1.h and l.cy - l1.cy < 4.5 * l1.h and _x_overlap(l, l1) > 0.5
            and len(_n(l.text)) >= 10
        ]
        below.sort(key=lambda l: l.cy)
        return [l1] + below[:2]
    l2 = lines[texts.index(found[1])]
    below = [l for l in lines if l.cy > l2.cy and l.cy - l2.cy < 2.5 * l2.h and _x_overlap(l, l2) > 0.5]
    return [l2] + sorted(below, key=lambda l: l.cy)[:1]


def _with_margin(left: float, top: float, w: float, h: float) -> Box:
    return Box(int(left - MARGIN * w), int(top - MARGIN * h), int(left + w * (1 + MARGIN)),
               int(top + h * (1 + MARGIN)))


def _back_box(mrz: list[Line]) -> Box:
    x0 = min(l.x0 for l in mrz)
    x1 = max(l.x1 for l in mrz)
    y1 = max(l.y1 for l in mrz)
    if len(mrz) < 3:
        y1 += int(1.2 * sum(l.h for l in mrz) / len(mrz)) * (3 - len(mrz))
    card_w = (x1 - x0) * BACK_W_PER_MRZ
    card_h = card_w / CARD_RATIO
    left = x0 - BACK_LEFT_OFFSET * card_w
    bottom = y1 + BACK_BOTTOM_OFFSET * card_h
    return _with_margin(left, bottom - card_h, card_w, card_h)


def _front_box_from_title(title: Line) -> Box:
    n = len(_n(title.text))
    w = title.w * min(1.5, max(1.0, 17 / max(n, 1)))
    card_w = w / TITLE_W_PER_CARD
    card_h = card_w / CARD_RATIO
    return _with_margin(title.x0 - TITLE_LEFT_OFFSET * card_w, title.y0 - TITLE_TOP_OFFSET * card_h, card_w, card_h)


def _front_box_from_header(header: Line) -> Box:
    n = len(_n(header.text))
    w = header.w * min(1.5, max(1.0, 30 / max(n, 1)))
    card_w = w / HEADER_W_PER_CARD
    card_h = card_w / CARD_RATIO
    return _with_margin(header.x0 - HEADER_LEFT_OFFSET * card_w, header.y0 - HEADER_TOP_OFFSET * card_h,
                        card_w, card_h)


def find_front(lines: list[Line], exclude: Box | None) -> tuple[Box | None, str | None]:
    def ok(l: Line) -> bool:
        return exclude is None or not exclude.contains(l.cx, l.cy)

    for l in lines:
        if not ok(l):
            continue
        t = is_title(l.text)
        if t and l.w > 3 * l.h:
            return _front_box_from_title(l), t
    # El reverso no trae el encabezado "INSTITUTO NACIONAL DE MIGRACIÓN": basta con verlo.
    for h in lines:
        if ok(h) and is_header(h.text) and h.w > 3 * h.h:
            return _front_box_from_header(h), None
    return None, None


def _lines_in(lines: list[Line], box: Box) -> list[Line]:
    return sorted((l for l in lines if box.contains(l.cx, l.cy)), key=lambda l: (l.cy, l.x0))


def _crop(img: np.ndarray, box: Box) -> np.ndarray:
    return img[box.y0:box.y1, box.x0:box.x1].copy()


def other_documents(lines: list[Line]) -> list[str]:
    """Otros documentos visibles en el OCR (no se extraen; se reportan)."""
    found: list[str] = []
    for l in lines:
        t = _n(l.text)
        if len(t) >= 20 and t.count("<") >= 2 and _PASSPORT_MRZ.match(t):
            found.append(f"pasaporte ({t[2:5]})")
        elif _INE_MRZ.match(t) or _fuzzy_in(t, "CREDENCIALPARAVOTAR") or _fuzzy_in(t, "INSTITUTONACIONALELECTORAL"):
            found.append("ine")
        elif _fuzzy_in(t, "LICENCIAPARACONDUCIR") or _fuzzy_in(t, "LICENCIADECONDUCIR") or t.startswith("LICENCIADEMANEJO"):
            found.append("licencia de conducir")
        elif t.startswith("PASAPORTE") or t.startswith("PASSPORT"):
            found.append("pasaporte")
        elif "FORMAMIGRATORIAMULTIPLE" in t:
            found.append("fmm")
        elif "DIRECCIONGENERALDEPROTOCOLO" in t or t.startswith("RELACIONESEXTERIORES"):
            found.append("acreditación diplomática (SRE)")
        elif "SOLICITUDUNICADE" in t or "TARJETADECREDITO" in t:
            found.append("solicitud bancaria")
        elif "SITUACIONFISCAL" in t:
            found.append("constancia del SAT")
    return list(dict.fromkeys(found))


def _locate(img: np.ndarray, lines: list[Line]):
    horiz = [l for l in lines if l.w >= l.h]
    mrz = find_mrz(horiz)
    h, w = img.shape[:2]
    back_box = _back_box(mrz).clip(w, h) if mrz else None
    if back_box is not None and back_box.area == 0:
        mrz, back_box = None, None
    front_box, tipo = find_front(horiz, back_box)
    if front_box is not None:
        front_box = front_box.clip(w, h)
        if front_box.area == 0:
            front_box = None
    return mrz, back_box, front_box, tipo


def _mostly_vertical(lines: list[Line]) -> bool:
    long = [l for l in lines if len(l.text) >= 6]
    return sum(l.h > 1.5 * l.w for l in long) > sum(l.w > 1.5 * l.h for l in long)


def _locate_with_rotations(img: np.ndarray, lines: list[Line], ocr_read):
    found = _locate(img, lines)
    if found[0] or found[2] or not lines:
        return img, lines, found, False
    likely = [90, 270] if _mostly_vertical(lines) else [180]
    for deg in likely + [d for d in (90, 180, 270) if d not in likely]:
        r_img = cv2.rotate(img, _ROTATIONS[deg])
        r_lines = ocr_read(r_img)
        r = _locate(r_img, r_lines)
        if r[0] or r[2]:
            return r_img, r_lines, r, True
    return img, lines, found, False


def analyze(pages: list[np.ndarray], ocr_read) -> Layout:
    front: Side | None = None
    back: Side | None = None
    warnings: list[str] = []
    rotated = False
    page_lines: list[list[Line]] = []
    page_images: list[np.ndarray] = []
    otros: list[str] = []

    for i, page in enumerate(pages):
        if front and back:
            page_images.append(page)
            page_lines.append([])
            continue
        img, lines, (mrz, back_box, front_box, tipo), rot = _locate_with_rotations(page, ocr_read(page), ocr_read)
        rotated = rotated or rot
        page_images.append(img)
        page_lines.append(lines)
        otros += other_documents(lines)
        if back is None and back_box:
            back = Side(i, back_box, _crop(img, back_box), _lines_in(lines, back_box), "ancla",
                        mrz_lines=[l.text for l in mrz])
        if front is None and front_box:
            front = Side(i, front_box, _crop(img, front_box), _lines_in(lines, front_box), "ancla")

    layout = Layout(front, back, rotated, len(pages), warnings, page_lines, page_images,
                    list(dict.fromkeys(otros)))
    _fill_missing(layout)
    return layout


def _fill_missing(layout: Layout) -> None:
    """Sin ancla: se manda la página completa al VLM para no perder el documento."""
    if layout.front is None and layout.page_images:
        idx = layout.back.page if layout.back else 0
        img, lines = layout.page_images[idx], layout.page_lines[idx]
        layout.front = Side(idx, Box(0, 0, img.shape[1], img.shape[0]), img, lines, "pagina_completa")
        layout.warnings.append("No se localizó el anverso; se analizó la página completa")
    if layout.back is None and layout.page_images:
        idx = layout.front.page if layout.front else 0
        img, lines = layout.page_images[idx], layout.page_lines[idx]
        layout.back = Side(idx, Box(0, 0, img.shape[1], img.shape[0]), img, lines, "pagina_completa")
        layout.warnings.append("No se localizó la MRZ del reverso; se analizó la página completa")


@dataclass
class CardBox:
    page: int
    box: Box
    lado: str
    rotacion: int = 0


def _box_sane(box: Box, w: int, h: int) -> bool:
    b = box.clip(w, h)
    frac = b.area / max(1, w * h)
    return 0.02 <= frac <= 0.95 and (b.x1 - b.x0) >= 80 and (b.y1 - b.y0) >= 50


def analyze_boxes(layout: Layout, cards: list[CardBox], ocr_read) -> Layout:
    """Reemplaza las caras sin ancla por los recortes del localizador (enderezados y ampliados)."""
    front = layout.front if layout.front and layout.front.method == "ancla" else None
    back = layout.back if layout.back and layout.back.method == "ancla" else None
    fallback_front = fallback_back = None
    used = 0

    for card in cards:
        if front and back:
            break
        if not (0 <= card.page < len(layout.page_images)):
            continue
        page = layout.page_images[card.page]
        h, w = page.shape[:2]
        if not _box_sane(card.box, w, h):
            continue
        box = card.box.clip(w, h)
        crop = _crop(page, box)
        if card.rotacion in _ROTATIONS:
            crop = cv2.rotate(crop, _ROTATIONS[card.rotacion])
        ch, cw = crop.shape[:2]
        if cw < CROP_MIN_WIDTH:
            scale = CROP_MIN_WIDTH / cw
            crop = cv2.resize(crop, (int(cw * scale), int(ch * scale)), interpolation=cv2.INTER_CUBIC)
        used += 1
        img, lines, (mrz, back_box, front_box, _tipo), _ = _locate_with_rotations(crop, ocr_read(crop), ocr_read)
        layout.page_lines[card.page] = layout.page_lines[card.page] + lines
        if back is None and back_box:
            back = Side(card.page, back_box, _crop(img, back_box), _lines_in(lines, back_box), "ancla",
                        mrz_lines=[l.text for l in mrz])
        if front is None and front_box:
            front = Side(card.page, front_box, _crop(img, front_box), _lines_in(lines, front_box), "ancla")
        if back_box or front_box:
            continue
        whole = Side(card.page, Box(0, 0, img.shape[1], img.shape[0]), img, lines, "localizador")
        if card.lado == "reverso" and fallback_back is None:
            fallback_back = whole
        elif card.lado == "anverso" and fallback_front is None:
            fallback_front = whole
        elif card.lado == "desconocido":
            if fallback_front is None:
                fallback_front = whole
            elif fallback_back is None:
                fallback_back = whole

    layout.front, layout.back = front or fallback_front, back or fallback_back
    layout.warnings = [w for w in layout.warnings if not w.startswith("No se localizó")]
    layout.warnings.append(
        f"Localizador: {len(cards)} caja(s), {used} usable(s), "
        f"{sum(s.method == 'ancla' for s in (layout.front, layout.back) if s)} con ancla")
    _fill_missing(layout)
    return layout
