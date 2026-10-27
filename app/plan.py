"""
Validaciones del "Plan de atención - Validación documental", sección Forma Migratoria.

Mismo módulo que en OCR-INM-DocumentAI (app/plan.py): trabaja sobre el JSON ya homologado
(`datos`, `mrz`, `clasificacion.categoria`) y no depende del motor de extracción, así que las dos
APIs responden el mismo bloque `validacion_plan`.

Responde las 8 preguntas del plan con SI / NO, en el mismo orden:

  1. ¿Es una hoja en blanco?              (pasa si NO)
  2. ¿La imagen es ilegible?              (pasa si NO)
  3. ¿Es una FM?                          (pasa si SI)
  4. ¿Está vigente?                       (pasa si SI)
  5. ¿El nombre coincide?                 (vs captura de la solicitud)
  6. ¿La CURP coincide?                   (vs captura, siempre y cuando exista el dato)
  7. ¿La fecha de nacimiento coincide?    (vs captura)
  8. ¿La nacionalidad coincide?           (vs captura)

Si no se cumplen al 100 %: mensaje "Revisar documento y motivo de rechazo" + motivos.

Valores de `resultado`:
  SI / NO          respuesta a la pregunta
  NO_APLICA        la comprobacion no corresponde (CURP sin dato en tarjeta o solicitud): no bloquea
  NO_VERIFICADO    faltan datos para responder (p. ej. no se envio el dato de la solicitud): bloquea
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Optional

from . import validators as v

MENSAJE_OK = "Documento válido: cumple con todas las validaciones."
MENSAJE_RECHAZO = "Revisar documento y motivo de rechazo"


@dataclass
class Solicitud:
    """Datos capturados en la solicitud. Todos opcionales."""
    nombre: Optional[str] = None             # nombre completo, en cualquier orden
    apellido_paterno: Optional[str] = None
    apellido_materno: Optional[str] = None
    nombres: Optional[str] = None
    curp: Optional[str] = None
    fecha_nacimiento: Optional[str] = None   # AAAA-MM-DD o DD/MM/AAAA
    nacionalidad: Optional[str] = None       # gentilicio, país o código ISO-3

    def nombre_completo(self) -> Optional[str]:
        if self.nombre and self.nombre.strip():
            return self.nombre
        partes = [p for p in (self.apellido_paterno, self.apellido_materno, self.nombres) if p and p.strip()]
        return " ".join(partes) or None

    def vacia(self) -> bool:
        return not any((self.nombre_completo(), self.curp, self.fecha_nacimiento, self.nacionalidad))


# ------------------------------------------------------------------ normalizacion


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().upper()


def _tokens(nombre: str) -> list[str]:
    return sorted(t for t in re.split(r"[^A-Z]+", _ascii(nombre)) if t)


def _fecha(s: Optional[str]) -> Optional[str]:
    if not s or not s.strip():
        return None
    s = s.strip()
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return None
    d = v.parse_date(s)  # DD/MM/AAAA, DD-MM-AAAA, "15 MAR 1990"
    return d.isoformat() if d else None


# Pares que el OCR confunde con frecuencia en la CURP
_CONFUNDIBLES = {frozenset(p) for p in ("O0", "I1", "S5", "B8", "Z2", "G6", "Q0", "D0")}


# ------------------------------------------------------------------ paises

# ISO-3 -> nombres y raices de gentilicio (sin acentos, mayúsculas). La raíz se compara
# contra el gentilicio sin su vocal final, para aceptar masculino y femenino.
_PAISES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "ARG": (("ARGENTINA",), ("ARGENTIN",)), "BOL": (("BOLIVIA",), ("BOLIVIAN",)),
    "BRA": (("BRASIL", "BRAZIL"), ("BRASILEN", "BRASILER")), "CHL": (("CHILE",), ("CHILEN",)),
    "COL": (("COLOMBIA",), ("COLOMBIAN",)), "CRI": (("COSTA RICA",), ("COSTARRICENS",)),
    "CUB": (("CUBA",), ("CUBAN",)), "DOM": (("REPUBLICA DOMINICANA",), ("DOMINICAN",)),
    "ECU": (("ECUADOR",), ("ECUATORIAN",)), "SLV": (("EL SALVADOR",), ("SALVADOREN",)),
    "GTM": (("GUATEMALA",), ("GUATEMALTEC",)), "HND": (("HONDURAS",), ("HONDUREN",)),
    "HTI": (("HAITI",), ("HAITIAN",)), "JAM": (("JAMAICA",), ("JAMAIQUIN", "JAMAICAN")),
    "MEX": (("MEXICO",), ("MEXICAN",)), "NIC": (("NICARAGUA",), ("NICARAGUENS",)),
    "PAN": (("PANAMA",), ("PANAMEN",)), "PRY": (("PARAGUAY",), ("PARAGUAY",)),
    "PER": (("PERU",), ("PERUAN",)), "PRI": (("PUERTO RICO",), ("PUERTORRIQUEN",)),
    "URY": (("URUGUAY",), ("URUGUAY",)), "VEN": (("VENEZUELA",), ("VENEZOLAN",)),
    "USA": (("ESTADOS UNIDOS", "ESTADOS UNIDOS DE AMERICA", "EUA", "EEUU", "USA"), ("ESTADOUNIDENS", "NORTEAMERICAN")),
    "CAN": (("CANADA",), ("CANADIENS",)), "ESP": (("ESPANA", "SPAIN"), ("ESPANOL",)),
    "PRT": (("PORTUGAL",), ("PORTUGUES",)), "FRA": (("FRANCIA", "FRANCE"), ("FRANCES",)),
    "ITA": (("ITALIA", "ITALY"), ("ITALIAN",)), "DEU": (("ALEMANIA", "GERMANY"), ("ALEMAN",)),
    "GBR": (("REINO UNIDO", "GRAN BRETANA", "INGLATERRA", "UNITED KINGDOM"), ("BRITANIC", "INGLES")),
    "IRL": (("IRLANDA",), ("IRLANDES",)), "NLD": (("PAISES BAJOS", "HOLANDA"), ("NEERLANDES", "HOLANDES")),
    "BEL": (("BELGICA",), ("BELG",)), "CHE": (("SUIZA",), ("SUIZ",)), "AUT": (("AUSTRIA",), ("AUSTRIAC",)),
    "SWE": (("SUECIA",), ("SUEC",)), "NOR": (("NORUEGA",), ("NORUEG",)), "DNK": (("DINAMARCA",), ("DANES",)),
    "FIN": (("FINLANDIA",), ("FINLANDES",)), "POL": (("POLONIA",), ("POLAC",)), "RUS": (("RUSIA",), ("RUS",)),
    "UKR": (("UCRANIA",), ("UCRANIAN",)), "ROU": (("RUMANIA",), ("RUMAN",)), "GRC": (("GRECIA",), ("GRIEG",)),
    "TUR": (("TURQUIA",), ("TURC",)), "ISR": (("ISRAEL",), ("ISRAELI",)), "LBN": (("LIBANO",), ("LIBANES",)),
    "CHN": (("CHINA",), ("CHIN",)), "JPN": (("JAPON",), ("JAPONES",)), "KOR": (("COREA DEL SUR", "COREA"), ("COREAN", "SURCOREAN")),
    "IND": (("INDIA",), ("INDI", "HINDU")), "PHL": (("FILIPINAS",), ("FILIPIN",)), "VNM": (("VIETNAM",), ("VIETNAMIT",)),
    "AUS": (("AUSTRALIA",), ("AUSTRALIAN",)), "NZL": (("NUEVA ZELANDA",), ("NEOZELANDES",)),
    "ZAF": (("SUDAFRICA",), ("SUDAFRICAN",)), "NGA": (("NIGERIA",), ("NIGERIAN",)), "EGY": (("EGIPTO",), ("EGIPCI",)),
    "MAR": (("MARRUECOS",), ("MARROQU",)), "IRN": (("IRAN",), ("IRANI",)), "PAK": (("PAKISTAN",), ("PAKISTANI",)),
}
_POR_CODIGO_ISO2 = {"AR": "ARG", "BO": "BOL", "BR": "BRA", "CL": "CHL", "CO": "COL", "CR": "CRI", "CU": "CUB",
                    "DO": "DOM", "EC": "ECU", "SV": "SLV", "GT": "GTM", "HN": "HND", "HT": "HTI", "MX": "MEX",
                    "NI": "NIC", "PA": "PAN", "PY": "PRY", "PE": "PER", "UY": "URY", "VE": "VEN", "US": "USA",
                    "CA": "CAN", "ES": "ESP", "PT": "PRT", "FR": "FRA", "IT": "ITA", "DE": "DEU", "GB": "GBR",
                    "CN": "CHN", "JP": "JPN", "KR": "KOR", "IN": "IND", "AU": "AUS", "IL": "ISR"}


def _raiz_gentilicio(s: str) -> str:
    s = re.sub(r"[^A-Z]", "", _ascii(s))
    return re.sub(r"(AS|OS|ES|A|O|E|S)$", "", s)


def pais_iso3(texto: Optional[str]) -> Optional[str]:
    """Convierte gentilicio, nombre de país o código (ISO-2/ISO-3) a ISO-3. None si no se reconoce."""
    if not texto or not texto.strip():
        return None
    t = re.sub(r"\s+", " ", _ascii(texto)).strip(" .")
    if t in _PAISES:
        return t
    if t in _POR_CODIGO_ISO2:
        return _POR_CODIGO_ISO2[t]
    raiz = _raiz_gentilicio(t)
    for iso, (nombres, raices) in _PAISES.items():
        if t in nombres or any(raiz == _raiz_gentilicio(r) or raiz.startswith(r) for r in raices):
            return iso
    return None


# ------------------------------------------------------------------ validaciones


def _item(id_: str, pregunta: str, resultado: str, ok: bool, detalle: str) -> dict:
    return {"id": id_, "pregunta": pregunta, "resultado": resultado, "ok": ok, "detalle": detalle}


def vigencia(datos: dict, regla: str = "anio", hoy: Optional[date] = None) -> tuple[Optional[bool], str]:
    """(vigente, detalle). regla 'anio': año de vigencia >= año actual (plan de atención).
    regla 'fecha': fecha de vencimiento >= hoy."""
    hoy = hoy or date.today()
    tipo = datos.get("tipo_documento")
    venc = datos.get("fecha_vencimiento")
    if tipo in ("RESIDENTE PERMANENTE", "INMIGRADO") and not venc:
        return True, "Residencia permanente: la tarjeta no tiene fecha de vencimiento."
    if not venc:
        return None, "No se pudo leer la fecha de vencimiento."
    v = date.fromisoformat(venc)
    if regla == "fecha":
        return v >= hoy, f"Vence el {venc}; se compara contra la fecha de hoy ({hoy.isoformat()})."
    return v.year >= hoy.year, f"Año de vigencia {v.year} contra año actual {hoy.year}."


def _ilegible(categoria: str, datos: dict, mrz: dict) -> tuple[bool, str]:
    if categoria == "hoja_en_blanco":
        return True, "No se leyó texto en el documento."
    if categoria != "forma_migratoria":
        return False, "Se leyó texto, pero el documento no es una forma migratoria."
    esenciales = {"nombre": datos.get("apellidos") or datos.get("nombres"), "fecha_nacimiento": datos.get("fecha_nacimiento"),
                  "numero_documento": datos.get("numero_documento"), "nue": datos.get("nue")}
    faltan = [k for k, v in esenciales.items() if not v]
    mrz_ok = "error" not in mrz
    if (not mrz_ok and faltan) or len(faltan) >= 2:
        return True, ("No se pudieron leer datos esenciales: " + ", ".join(faltan)
                      + ("; la MRZ del reverso tampoco es legible." if not mrz_ok else "."))
    return False, "Los datos esenciales se leyeron" + (" y la MRZ es legible." if mrz_ok else "; la MRZ no es legible.")


def _comparar_nombre(doc: Optional[str], sol: Optional[str]) -> tuple[str, bool, str]:
    if not sol:
        return "NO_VERIFICADO", False, "No se envió el nombre de la solicitud."
    if not doc:
        return "NO_VERIFICADO", False, "No se pudo leer el nombre en la tarjeta."
    a, b = _tokens(doc), _tokens(sol)
    if a == b:
        return "SI", True, "El nombre coincide con la captura (sin importar orden, acentos ni mayúsculas)."
    faltan = sorted(set(b) - set(a))
    sobran = sorted(set(a) - set(b))
    det = "El nombre no coincide."
    if faltan:
        det += f" En la solicitud y no en la tarjeta: {' '.join(faltan)}."
    if sobran:
        det += f" En la tarjeta y no en la solicitud: {' '.join(sobran)}."
    return "NO", False, det


def _comparar_curp(doc: Optional[str], sol: Optional[str], datos: dict) -> tuple[str, bool, str]:
    if not sol:
        return "NO_APLICA", True, "La solicitud no trae CURP."
    sol_n = re.sub(r"[^A-Z0-9]", "", _ascii(sol))
    if not doc:
        return "NO_APLICA", True, "La tarjeta no trae CURP legible."
    if doc == sol_n:
        return "SI", True, "La CURP coincide con la captura."
    if len(doc) == len(sol_n) == 18:
        difs = [(x, y) for x, y in zip(doc, sol_n) if x != y]
        if len(difs) <= 2 and all(frozenset((x, y)) in _CONFUNDIBLES for x, y in difs):
            # La lectura de la tarjeta difiere solo en caracteres que el OCR confunde.
            # Se acepta si la CURP capturada es coherente con los datos verificados por la MRZ.
            fn, sexo = datos.get("fecha_nacimiento"), datos.get("sexo")
            fecha_ok = bool(fn) and sol_n[4:10] == fn[2:4] + fn[5:7] + fn[8:10]
            sexo_ok = sexo not in ("H", "M") or sol_n[10] == sexo
            if fecha_ok and sexo_ok:
                return "SI", True, ("La CURP coincide; la lectura de la tarjeta difiere solo en "
                                    f"{len(difs)} carácter(es) que el OCR suele confundir, y la CURP capturada "
                                    "es coherente con la fecha de nacimiento y el sexo verificados.")
    return "NO", False, f"La CURP no coincide: tarjeta '{doc}' vs solicitud '{sol_n}'."


def _comparar_fecha(doc: Optional[str], sol: Optional[str]) -> tuple[str, bool, str]:
    if not sol:
        return "NO_VERIFICADO", False, "No se envió la fecha de nacimiento de la solicitud."
    sol_f = _fecha(sol)
    if not sol_f:
        return "NO_VERIFICADO", False, f"La fecha de la solicitud '{sol}' no tiene un formato reconocible (usar AAAA-MM-DD)."
    if not doc:
        return "NO_VERIFICADO", False, "No se pudo leer la fecha de nacimiento en la tarjeta."
    if doc == sol_f:
        return "SI", True, "La fecha de nacimiento coincide con la captura."
    return "NO", False, f"La fecha de nacimiento no coincide: tarjeta {doc} vs solicitud {sol_f}."


def _comparar_nacionalidad(datos: dict, sol: Optional[str]) -> tuple[str, bool, str]:
    if not sol:
        return "NO_VERIFICADO", False, "No se envió la nacionalidad de la solicitud."
    doc_iso = datos.get("pais") or pais_iso3(datos.get("nacionalidad"))
    if not doc_iso and not datos.get("nacionalidad"):
        return "NO_VERIFICADO", False, "No se pudo leer la nacionalidad en la tarjeta."
    sol_iso = pais_iso3(sol)
    if sol_iso and doc_iso:
        if sol_iso == doc_iso:
            return "SI", True, f"La nacionalidad coincide ({doc_iso})."
        return "NO", False, f"La nacionalidad no coincide: tarjeta {doc_iso} vs solicitud {sol_iso} ('{sol}')."
    # País no reconocido en el catálogo: se compara el gentilicio sin su terminación
    doc_g = datos.get("nacionalidad") or ""
    if doc_g and _raiz_gentilicio(doc_g) == _raiz_gentilicio(sol):
        return "SI", True, f"La nacionalidad coincide ({doc_g})."
    return "NO", False, (f"La nacionalidad no coincide o no se reconoce: tarjeta '{doc_g or doc_iso}' vs solicitud '{sol}'.")


def evaluar(categoria: str, datos: Optional[dict], mrz: Optional[dict], solicitud: Solicitud,
            regla_vigencia: str = "anio") -> dict:
    """Arma el bloque validacion_plan. categoria: forma_migratoria | otro | hoja_en_blanco."""
    datos, mrz = datos or {}, mrz or {}
    es_fm = categoria == "forma_migratoria"
    items: list[dict] = []

    blanco = categoria == "hoja_en_blanco"
    items.append(_item("hoja_en_blanco", "¿Es una hoja en blanco?", "SI" if blanco else "NO", not blanco,
                       "No se leyó texto en el documento." if blanco else "El documento tiene contenido."))

    ileg, det = _ilegible(categoria, datos, mrz)
    items.append(_item("imagen_ilegible", "¿La imagen es ilegible?", "SI" if ileg else "NO", not ileg, det))

    items.append(_item("es_forma_migratoria", "¿Es una FM?", "SI" if es_fm else "NO", es_fm,
                       "Se identificó una tarjeta de residente del INM." if es_fm
                       else "El documento no es una tarjeta de residente del INM."))

    if es_fm:
        vig, det = vigencia(datos, regla_vigencia)
        res = "NO_VERIFICADO" if vig is None else ("SI" if vig else "NO")
        items.append(_item("vigente", "¿Está vigente?", res, bool(vig), det))
        r, ok, det = _comparar_nombre(datos.get("nombre_completo"), solicitud.nombre_completo())
        items.append(_item("nombre_coincide", "¿El nombre coincide?", r, ok, det))
        r, ok, det = _comparar_curp(datos.get("curp"), solicitud.curp, datos)
        items.append(_item("curp_coincide", "¿La CURP coincide?", r, ok, det))
        r, ok, det = _comparar_fecha(datos.get("fecha_nacimiento"), solicitud.fecha_nacimiento)
        items.append(_item("fecha_nacimiento_coincide", "¿La fecha de nacimiento coincide?", r, ok, det))
        r, ok, det = _comparar_nacionalidad(datos, solicitud.nacionalidad)
        items.append(_item("nacionalidad_coincide", "¿La nacionalidad coincide?", r, ok, det))
    else:
        for id_, preg in (("vigente", "¿Está vigente?"), ("nombre_coincide", "¿El nombre coincide?"),
                          ("curp_coincide", "¿La CURP coincide?"),
                          ("fecha_nacimiento_coincide", "¿La fecha de nacimiento coincide?"),
                          ("nacionalidad_coincide", "¿La nacionalidad coincide?")):
            items.append(_item(id_, preg, "NO_VERIFICADO", False, "No aplica: el documento no es una forma migratoria."))

    cumple = all(i["ok"] for i in items)
    # Motivos de raiz: si no es FM, las validaciones que dependen de ello no se repiten como motivo.
    motivos = [f"{i['pregunta']} {i['resultado']}: {i['detalle']}" for i in items
               if not i["ok"] and not i["detalle"].startswith("No aplica: el documento no es")]
    if es_fm and solicitud.vacia():
        motivos.append("No se enviaron datos de la solicitud: las validaciones de coincidencia no se pudieron realizar.")
    return {"cumple": cumple, "mensaje": MENSAJE_OK if cumple else MENSAJE_RECHAZO,
            "motivos_rechazo": motivos, "regla_vigencia": regla_vigencia, "validaciones": items}
