"""Validaciones de CURP (extranjeros: entidad "NE") y utilidades de texto y fechas."""

import re
import unicodedata
from datetime import date
from difflib import SequenceMatcher

CURP_STATES = {
    "AS", "BC", "BS", "CC", "CL", "CM", "CS", "CH", "DF", "DG", "GT", "GR", "HG", "JC", "MC",
    "MN", "MS", "NT", "NL", "OC", "PL", "QT", "QR", "SP", "SL", "SR", "TC", "TS", "TL", "VZ",
    "YN", "ZS", "NE",
}
CURP_RE = re.compile(r"^[A-Z][AEIOUX][A-Z]{2}\d{6}[HMX][A-Z]{2}[B-DF-HJ-NP-TV-Z]{3}[0-9A-Z]\d$")
NUE_RE = re.compile(r"^\d{13}$")
SEGOB_RE = re.compile(r"^SEGOB-INM-\d{6,10}$")

_CURP_ALPHABET = "0123456789ABCDEFGHIJKLMNÑOPQRSTUVWXYZ"
_TO_DIGIT = str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2",
                           "S": "5", "B": "8", "G": "6", "T": "7"})
_TO_ALPHA = str.maketrans({"0": "O", "1": "I", "2": "Z", "5": "S", "8": "B", "6": "G", "4": "A"})

# Nacionalidad impresa (gentilicio) -> código ISO 3166-1 alfa-3 que trae la MRZ
GENTILICIO_ISO = {
    "MEXICANA": "MEX", "MEXICANO": "MEX", "ESPANOLA": "ESP", "ESPANOL": "ESP", "COLOMBIANA": "COL",
    "COLOMBIANO": "COL", "VENEZOLANA": "VEN", "VENEZOLANO": "VEN", "ARGENTINA": "ARG", "ARGENTINO": "ARG",
    "CUBANA": "CUB", "CUBANO": "CUB", "BRASILENA": "BRA", "BRASILENO": "BRA", "BRASILEIRA": "BRA",
    "CHILENA": "CHL", "CHILENO": "CHL", "PERUANA": "PER", "PERUANO": "PER", "ITALIANA": "ITA",
    "ITALIANO": "ITA", "ESTADOUNIDENSE": "USA", "AMERICANA": "USA", "AMERICANO": "USA",
    "HONDURENA": "HND", "HONDURENO": "HND", "CANADIENSE": "CAN", "ECUATORIANA": "ECU",
    "ECUATORIANO": "ECU", "FRANCESA": "FRA", "FRANCES": "FRA", "COSTARRICENSE": "CRI",
    "SALVADORENA": "SLV", "SALVADORENO": "SLV", "HAITIANA": "HTI", "HAITIANO": "HTI", "CHINA": "CHN",
    "CHINO": "CHN", "ALEMANA": "DEU", "ALEMAN": "DEU", "ISRAELI": "ISR", "BOLIVIANA": "BOL",
    "BOLIVIANO": "BOL", "URUGUAYA": "URY", "URUGUAYO": "URY", "GUATEMALTECA": "GTM",
    "GUATEMALTECO": "GTM", "PORTUGUESA": "PRT", "PORTUGUES": "PRT", "POLACA": "POL", "POLACO": "POL",
    "JAPONESA": "JPN", "JAPONES": "JPN", "BRITANICA": "GBR", "BRITANICO": "GBR", "INDIA": "IND",
    "INDIO": "IND", "NICARAGUENSE": "NIC", "PARAGUAYA": "PRY", "PARAGUAYO": "PRY", "COREANA": "KOR",
    "COREANO": "KOR", "DE LA REPUBLICA DE COREA": "KOR", "RUSA": "RUS", "RUSO": "RUS", "DOMINICANA": "DOM",
    "DOMINICANO": "DOM", "PANAMENA": "PAN", "PANAMENO": "PAN", "NIGERIANA": "NGA", "NIGERIANO": "NGA",
    "SUIZA": "CHE", "SUIZO": "CHE", "HOLANDESA": "NLD", "HOLANDES": "NLD", "NEERLANDESA": "NLD",
    "BELGA": "BEL", "SUECA": "SWE", "SUECO": "SWE", "TURCA": "TUR", "TURCO": "TUR", "AUSTRALIANA": "AUS",
    "AUSTRALIANO": "AUS", "FILIPINA": "PHL", "FILIPINO": "PHL", "IRLANDESA": "IRL", "IRLANDES": "IRL",
    "UCRANIANA": "UKR", "UCRANIANO": "UKR", "TAIWANESA": "TWN", "TAIWANES": "TWN",
}


def strip_accents(s: str) -> str:
    s = s.replace("Ñ", "\0").replace("ñ", "\0")
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return s.replace("\0", "Ñ")


def norm_text(s: str | None) -> str:
    """Mayúsculas, sin acentos (Ñ -> N), espacios simples."""
    if not s:
        return ""
    s = strip_accents(s.upper()).replace("Ñ", "N")
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", s)).strip()


def _typed(s: str, kinds: str) -> str:
    out = []
    for ch, k in zip(s, kinds):
        if k == "d":
            ch = ch.translate(_TO_DIGIT)
        elif k == "a":
            ch = ch.translate(_TO_ALPHA)
        out.append(ch)
    return "".join(out)


# ------------------------------------------------------------------- CURP


def curp_check_digit(curp17: str) -> str:
    total = sum(_CURP_ALPHABET.index(c) * (18 - i) for i, c in enumerate(curp17))
    return str((10 - total % 10) % 10)


def normalize_curp(raw: str | None) -> str | None:
    if not raw:
        return None
    s = re.sub(r"[^A-Z0-9Ñ]", "", strip_accents(raw.upper()))
    if len(s) != 18:
        return s or None
    return _typed(s, "aaaa" + "dddddd" + "a" + "aa" + "aaa" + "*" + "d")


def curp_valid(curp: str | None) -> bool:
    if not curp or not CURP_RE.match(curp) or curp[11:13] not in CURP_STATES:
        return False
    bd = curp_birthdate(curp)
    if bd is None or bd > date.today():
        return False  # una letra en la posición 17 implica nacido en 2000+; si cae en el futuro es O/0 mal leída
    return curp_check_digit(curp[:17]) == curp[17]


def curp_birthdate(curp: str) -> date | None:
    try:
        yy, mm, dd = int(curp[4:6]), int(curp[6:8]), int(curp[8:10])
        century = 2000 if curp[16].isalpha() else 1900
        return date(century + yy, mm, dd)
    except (ValueError, IndexError):
        return None


def curp_sex(curp: str) -> str | None:
    return curp[10] if len(curp) == 18 and curp[10] in "HMX" else None


_VOWELS = set("AEIOU")
_SKIP_FIRST = {"MARIA", "MA", "MA.", "JOSE", "J", "J."}
_PARTICLES = {"DA", "DAS", "DE", "DEL", "DER", "DI", "DIE", "DD", "EL", "LA", "LOS", "LAS",
              "LE", "LES", "MAC", "MC", "VAN", "VON", "Y"}


def _main_word(name: str, skip_common_first: bool = False) -> str:
    clean = re.sub(r"[^A-ZÑ ]", " ", strip_accents(name.upper()))
    words = [w for w in clean.split() if w not in _PARTICLES]
    if skip_common_first and len(words) > 1 and words[0] in _SKIP_FIRST:
        words = words[1:]
    return words[0] if words else ""


def _first_inner(word: str, consonant: bool, fallback: str = "X") -> str:
    for ch in word[1:]:
        if ch == "Ñ":
            continue
        if ch.isalpha() and ((ch not in _VOWELS) == consonant):
            return ch
    return fallback


# Palabras que el RENAPO no permite como inicio de CURP: la segunda letra se sustituye por X (CAGA -> CXGA)
ALTISONANTES = {
    "BACA", "BAKA", "BUEI", "BUEY", "CACA", "CACO", "CAGA", "CAGO", "CAKA", "CAKO", "COGE", "COGI", "COJA", "COJE",
    "COJI", "COJO", "COLA", "CULO", "FALO", "FETO", "GETA", "GUEI", "GUEY", "JETA", "JOTO", "KACA", "KACO", "KAGA",
    "KAGO", "KAKA", "KAKO", "KOGE", "KOGI", "KOJA", "KOJE", "KOJI", "KOJO", "KOLA", "KULO", "LILO", "LOCA", "LOCO",
    "LOKA", "LOKO", "MAME", "MAMO", "MEAR", "MEAS", "MEON", "MIAR", "MION", "MOCO", "MOKO", "MULA", "MULO", "NACA",
    "NACO", "PEDA", "PEDO", "PENE", "PIPI", "PITO", "POPO", "PUTA", "PUTO", "QULO", "RATA", "ROBA", "ROBE", "ROBO",
    "RUIN", "SENO", "TETA", "VACA", "VAGA", "VAGO", "VAKA", "VUEI", "VUEY", "WUEI", "WUEY",
}


def curp_name_prefix(paterno: str | None, materno: str | None, nombres: str | None) -> str | None:
    """Las 4 letras iniciales esperadas de la CURP. Para extranjeros sin segundo apellido la 3ª es X."""
    p = _main_word(paterno or "")
    n = _main_word(nombres or "", skip_common_first=True)
    if not p or not n:
        return None
    m = _main_word(materno or "")
    prefix = (p[0] + _first_inner(p, consonant=False) + (m[0] if m else "X") + n[0]).replace("Ñ", "X")
    if prefix in ALTISONANTES:
        prefix = prefix[0] + "X" + prefix[2:]
    return prefix


def names_match(front: str | None, mrz: str | None) -> bool:
    """El renglón 3 de la MRZ del INM trunca cada palabra (JIMENEZ -> JIMEN) y el OCR cambia letras:
    cada palabra de la MRZ debe ser prefijo (o casi igual) de la palabra correspondiente del anverso."""
    a, b = norm_text(front).split(), norm_text(mrz).split()
    if not a or not b:
        return False
    if len(b) > len(a) + 1:
        return False
    i = 0
    skipped = False
    for w in b:
        if i >= len(a):
            return len(w) <= 2  # relleno suelto al final
        cand = a[i]
        ok = cand.startswith(w) or w.startswith(cand) or (len(w) >= 4 and similarity(cand[:len(w)], w) >= 0.75)
        if not ok:
            # palabra pegada o partida en la MRZ: intenta con la siguiente del anverso
            if i + 1 < len(a) and (a[i] + a[i + 1]).startswith(w):
                i += 2
                continue
            # la MRZ omitió una palabra del anverso (p. ej. el segundo apellido): se salta UNA vez
            if not skipped and i + 1 < len(a) and len(a) > len(b):
                nxt = a[i + 1]
                if nxt.startswith(w) or w.startswith(nxt) or (len(w) >= 4 and similarity(nxt[:len(w)], w) >= 0.75):
                    skipped = True
                    i += 2
                    continue
            return False
        i += 1
    return True


def similarity(a: str | None, b: str | None) -> float:
    a, b = norm_text(a), norm_text(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def word_overlap(a: str | None, b: str | None) -> float:
    """Fracción de palabras de la cadena más corta que aparecen en la otra."""
    wa, wb = set(norm_text(a).split()), set(norm_text(b).split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


_MONTHS = {"ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AGO": 8, "SEP": 9,
           "OCT": 10, "NOV": 11, "DIC": 12, "JAN": 1, "APR": 4, "AUG": 8, "DEC": 12}


def parse_date(s: str | None) -> date | None:
    if not s:
        return None
    m = re.search(r"(\d{1,2})\s*[/\-. ]\s*(\d{1,2})\s*[/\-. ]\s*(\d{4})", s)
    if m:
        try:
            return date(int(m[3]), int(m[2]), int(m[1]))
        except ValueError:
            return None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    m = re.search(r"(\d{1,2})\s*[/\-. ]?\s*([A-Z]{3})[A-Z]*\s*[/\-. ]?\s*(\d{4})", strip_accents(s.upper()))
    if m and m[2] in _MONTHS:
        try:
            return date(int(m[3]), _MONTHS[m[2]], int(m[1]))
        except ValueError:
            return None
    return None


def normalize_sex(s: str | None) -> str | None:
    """Lo impreso (Hombre / Mujer / Masculino / Femenino / M / F / H) -> H / M / X."""
    t = norm_text(s)
    if not t:
        return None
    if t in ("H", "HOMBRE", "MASCULINO", "MALE", "M") and t != "M":
        return "H"
    if t == "M":
        return "M"  # ambiguo: en la tarjeta "M" no se imprime; en la MRZ M = hombre (se trata aparte)
    if t in ("MUJER", "FEMENINO", "FEMALE", "F"):
        return "M"
    if t.startswith("X") or t == "NO BINARIO":
        return "X"
    return None


def nationality_iso(printed: str | None) -> str | None:
    t = norm_text(printed)
    if not t:
        return None
    if re.fullmatch(r"[A-Z]{3}", t):
        return t
    return GENTILICIO_ISO.get(t) or GENTILICIO_ISO.get(t.split()[0] if t.split() else "")


# Oficinas del INM que encabezan "Impreso en" / "Expedido en": OR (Oficina de Representación), SRF (Subrepresentación
# Federal), RL (Representación Local), AI (Aeropuerto Internacional), Delegación Federal/Local, Oficina de Representación
_OFICINA_RE = re.compile(r"((?:OR|SRF|RL|AI|SR|OF)\s+[A-Z]|DELEGACION|O?FICINAS?\s+DE|SUB\s*REPRESENTACION|REPRESENTACION\s+)")


def limpiar_lugar(s: str | None) -> str | None:
    """Quita la etiqueta ("Impreso en:", "!mpre50 en", "IMPRASA CN") que el OCR o el VLM pegan antes de la oficina
    y la fecha que va después de la coma. 'MPRESO EN SRF COZUMEL, 25/10/2023' -> 'SRF COZUMEL, 25/10/2023'."""
    if not s:
        return None
    up = strip_accents(s.upper())
    up = re.sub(r"^\s*AL\s+(?=[A-Z])", "AI ", up)  # "Al PUERTO ESCONDIDO": la I se lee como l
    m = _OFICINA_RE.search(up)
    if m and m.start() > 0:
        s = s[m.start():]
    s = re.sub(r"^\s*(EXPEDIDO|IMPRESO)\s*EN\s*:?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^\s*A[Ll]\s+(?=[A-Z])", "AI ", s)
    s = re.sub(r"^\s*FICINA", "OFICINA", s, flags=re.IGNORECASE)  # "Oficina" sin la O inicial
    return re.sub(r"\s+", " ", s).strip(" ,:-") or None
