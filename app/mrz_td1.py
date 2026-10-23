"""Lectura de la MRZ TD1 (3 líneas x 30 caracteres, ICAO 9303) de la tarjeta de residente del INM.

Estructura (igual en Residente Temporal y Permanente):

    Línea 1: I<MEX + número de documento (9, p. ej. "12345678<") + dígito + opcional (15)
    Línea 2: nacimiento AAMMDD + dígito + sexo (M/F) + fecha AAMMDD + dígito + nacionalidad (3)
             + opcional (11) + dígito compuesto
    Línea 3: APELLIDO1<APELLIDO2<<NOMBRE1<NOMBRE2 (truncado a 30)

OJO: en la posición que ICAO reserva al vencimiento, el INM imprime la FECHA DE EXPEDICIÓN de la
tarjeta (comprobado contra el anverso en el lote). En Residente Permanente viene vacía ("<<<<<<").

Los errores típicos del OCR (O/0, I/1, S/5, B/8...) se corrigen según el tipo de cada posición, y
si un dígito verificador no cuadra se intenta una sola sustitución entre caracteres confusables.
"""

import re
from dataclasses import dataclass, field
from datetime import date

LINE_LEN = 30

_TO_DIGIT = str.maketrans({"O": "0", "Q": "0", "D": "0", "U": "0", "I": "1", "L": "1", "T": "1",
                           "Z": "2", "S": "5", "B": "8", "G": "6", "A": "4", "E": "8"})
_TO_ALPHA = str.maketrans({"0": "O", "1": "I", "2": "Z", "5": "S", "8": "B", "6": "G", "4": "A"})
_FILLER_LIKE = str.maketrans({"(": "<", "[": "<", "{": "<", "‹": "<", "«": "<", "K": "<", "C": "<"})

_CONFUSABLE = {
    "0": "86935", "1": "74", "2": "7", "3": "8956", "4": "19", "5": "6389",
    "6": "5803", "7": "12", "8": "035693", "9": "830",
}


def check_digit(s: str) -> int:
    weights = (7, 3, 1)
    total = 0
    for i, ch in enumerate(s):
        if ch.isdigit():
            v = int(ch)
        elif "A" <= ch <= "Z":
            v = ord(ch) - 55
        else:
            v = 0
        total += v * weights[i % 3]
    return total % 10


@dataclass
class MrzCheck:
    nombre: str
    valido: bool
    corregido: bool = False


@dataclass
class MrzResult:
    lineas: list[str]
    numero_documento: str | None = None
    fecha_nacimiento: date | None = None
    sexo: str | None = None  # "H" / "M" (impreso en la MRZ como M / F)
    sexo_mrz: str | None = None
    fecha_expedicion: date | None = None  # campo "vencimiento" de ICAO; el INM pone ahí la expedición
    sin_fecha: bool = False  # Residente Permanente: campo vacío
    nacionalidad: str | None = None
    apellidos: str | None = None
    nombres: str | None = None
    checks: list[MrzCheck] = field(default_factory=list)

    @property
    def valido(self) -> bool:
        return bool(self.checks) and all(c.valido for c in self.checks)

    @property
    def corregido(self) -> bool:
        return any(c.corregido for c in self.checks)

    @property
    def n_validos(self) -> int:
        return sum(c.valido for c in self.checks)


# ---------------------------------------------------------------- normalización


def _clean(s: str) -> str:
    return s.upper().replace(" ", "").replace("«", "<<")


def _fit(s: str) -> str:
    return (s + "<" * LINE_LEN)[:LINE_LEN]


def _map(s: str, kind: str) -> str:
    """kind por carácter: d=dígito, a=letra, f=relleno, x=dígito o '<', n=letra o '<', *=libre."""
    out = []
    for ch, k in zip(s, kind):
        if k == "d":
            ch = ch.translate(_TO_DIGIT)
        elif k == "a":
            ch = ch.translate(_TO_ALPHA)
        elif k == "f":
            ch = "<"
        elif k == "x":
            ch = ch.translate(_FILLER_LIKE)
            if ch != "<":
                ch = ch.translate(_TO_DIGIT)
        elif k == "n":
            ch = ch.translate(_FILLER_LIKE) if ch in "([{‹«" else ch
            if ch != "<":
                ch = ch.translate(_TO_ALPHA)
        out.append(ch)
    return "".join(out)


# número: 8 dígitos + relleno (se deja "x" para no forzar el '<' final); dígito; opcional de relleno
L1_KIND = "fffff" + "x" * 9 + "d" + "x" * 15
L2_KIND = "d" * 6 + "d" + "a" + "x" * 6 + "x" + "aaa" + "x" * 11 + "d"
L3_KIND = "n" * 30

_HEAD = re.compile(r"^[1IL]?[<KC(]?[MN][EF3][XK]")


def normalize_line1(raw: str) -> str:
    s = _clean(raw)
    m = _HEAD.search(s)
    if m:
        s = "I<MEX" + s[m.end():]
    s = _fit(s)
    s = _map(s, L1_KIND)
    return "I<MEX" + s[5:]


def normalize_line2(raw: str) -> str:
    s = _fit(_clean(raw))
    s = _map(s, L2_KIND)
    if s[7] not in "MFX<":
        s = s[:7] + {"N": "M", "W": "M", "H": "M", "E": "F", "P": "F", "4": "M"}.get(s[7], s[7]) + s[8:]
    return s


def normalize_line3(raw: str) -> str:
    return _map(_fit(_clean(raw)), L3_KIND)


# ---------------------------------------------------------------- reparación


def _repair_candidates(value: str, expected: str) -> list[tuple[str, str]]:
    candidates = set()
    for i, ch in enumerate(value):
        for alt in _CONFUSABLE.get(ch, ""):
            cand = value[:i] + alt + value[i + 1:]
            if str(check_digit(cand)) == expected:
                candidates.add((cand, expected))
    for alt in _CONFUSABLE.get(expected, ""):
        if str(check_digit(value)) == alt:
            candidates.add((value, alt))
    return sorted(candidates)


def _has_content(value: str) -> bool:
    core = value.rstrip("<")
    return core.isdigit() and core.strip("0") != ""


def _date(yymmdd: str, *, future: bool) -> date | None:
    if not yymmdd.isdigit():
        return None
    yy, mm, dd = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
    if future:
        year = 2000 + yy
    else:
        year = 2000 + yy if yy <= date.today().year % 100 else 1900 + yy
    try:
        return date(year, mm, dd)
    except ValueError:
        return None


def _composite(l1: str, l2: str) -> str:
    return l1[5:30] + l2[0:7] + l2[8:15] + l2[18:29]


def _composite_ok(l1: str, l2: str) -> bool:
    if not (_has_content(l1[5:14]) and _has_content(l2[0:6])):
        return False
    return l2[29].isdigit() and str(check_digit(_composite(l1, l2))) == l2[29]


def _verify(l1: str, l2: str, start: int, length: int, line: int, nombre: str,
            checks: list[MrzCheck]) -> tuple[str, str]:
    lines = [l1, l2]
    src = lines[line]
    value, expected = src[start:start + length], src[start + length]
    if not _has_content(value):
        checks.append(MrzCheck(nombre, False))
        return l1, l2
    if expected.isdigit() and str(check_digit(value)) == expected:
        checks.append(MrzCheck(nombre, True))
        return l1, l2
    options = []
    if expected.isdigit():
        for cand, digit in _repair_candidates(value, expected):
            if nombre != "mrz_numero" and _date(cand, future=False) is None:
                continue
            if nombre == "mrz_numero" and not re.fullmatch(r"\d{7,9}<*", cand):
                continue
            fixed = lines.copy()
            fixed[line] = src[:start] + cand + digit + src[start + length + 1:]
            options.append(fixed)
    if len(options) > 1:
        options = [o for o in options if _composite_ok(o[0], o[1])]
    if len(options) == 1:
        checks.append(MrzCheck(nombre, True, corregido=True))
        return options[0][0], options[0][1]
    checks.append(MrzCheck(nombre, False))
    return l1, l2


# ---------------------------------------------------------------- parseo


def _names(l3: str) -> tuple[str | None, str | None]:
    parts = l3.rstrip("<").split("<<", 1)
    surnames = " ".join(p for p in parts[0].split("<") if p) or None
    given = " ".join(p for p in parts[1].split("<") if p) if len(parts) > 1 else None
    return surnames, given or None


def parse(lines: list[str]) -> MrzResult | None:
    """Recibe las 3 líneas crudas (en orden) y devuelve los datos con sus validaciones."""
    if len(lines) < 2 or not lines[1]:
        return None
    l1 = normalize_line1(lines[0] or "")
    l2 = normalize_line2(lines[1])
    l3 = normalize_line3(lines[2]) if len(lines) > 2 and lines[2] else None

    checks: list[MrzCheck] = []
    l1, l2 = _verify(l1, l2, 5, 9, 0, "mrz_numero", checks)
    l1, l2 = _verify(l1, l2, 0, 6, 1, "mrz_fecha_nacimiento", checks)
    sin_fecha = l2[8:14].strip("<") == "" or (l2[8:14] == "000000")
    if not sin_fecha:
        l1, l2 = _verify(l1, l2, 8, 6, 1, "mrz_fecha_expedicion", checks)
    checks.append(MrzCheck("mrz_compuesto", _composite_ok(l1, l2)))

    r = MrzResult(lineas=[l1, l2] + ([l3] if l3 else []), checks=checks)
    num = l1[5:14].rstrip("<")
    r.numero_documento = num if num.isdigit() and len(num) >= 7 else None
    r.fecha_nacimiento = _date(l2[0:6], future=False)
    r.sexo_mrz = l2[7] if l2[7] in "MFX" else None
    r.sexo = {"M": "H", "F": "M", "X": "X"}.get(r.sexo_mrz or "", None)
    r.sin_fecha = sin_fecha
    r.fecha_expedicion = None if sin_fecha else _date(l2[8:14], future=False)
    nac = l2[15:18]
    r.nacionalidad = nac if re.fullmatch(r"[A-Z]{3}", nac) else None
    if l3:
        r.apellidos, r.nombres = _names(l3)
    return r


def best(*candidates: MrzResult | None) -> MrzResult | None:
    valid = [c for c in candidates if c is not None]
    if not valid:
        return None
    return max(valid, key=lambda c: (c.n_validos, not c.corregido, bool(c.nombres)))


_L1 = re.compile(r"^[1IL]?[<KC(]?[MN][EF3][XK][0-9OQDILSBZ]{6}")
_L2 = re.compile(r"^\d{6}[0-9OD][MFX][0-9OD<]{7}[A-Z]{3}")


def find_mrz_lines(texts: list[str]) -> list[str] | None:
    """Ubica las 3 líneas MRZ dentro de una lista de textos (ordenados de arriba abajo)."""
    for i, t in enumerate(texts):
        c = re.sub(r"[^A-Z0-9<]", "", _clean(t))
        if _L1.search(c) and not c.startswith("IDMEX") and c.count("<") >= 2:
            return texts[i:i + 3]
    for i, t in enumerate(texts):
        c = re.sub(r"[^A-Z0-9<]", "", _clean(t))
        m = _L2.search(c)
        if m and len(c) >= 20:
            if c[15:18] == "MEX" or (i > 0 and re.search(r"[1IL]?D[MN]EX", _clean(texts[i - 1]))):
                continue  # nacionalidad MEX = credencial INE (IDMEX), no tarjeta de residente
            return [""] + [texts[i]] + ([texts[i + 1]] if i + 1 < len(texts) else [])
    return None
