"""Combina VLM (anverso y reverso) + OCR + MRZ, valida y asigna confianza por campo.

Criterio de confianza:
* alta  — dos fuentes independientes coinciden, o un dígito verificador lo respalda (MRZ, CURP).
* media — una sola fuente con estructura válida, sin contradicciones.
* baja  — fuentes en desacuerdo, estructura inválida o campo vacío.

El documento queda en "revisar" si algún campo crítico tiene confianza baja.
"""

import re
from datetime import date

from . import validators as v
from .front_ocr import FrontOcr
from .mrz_td1 import MrzResult
from .schemas import Confianza, DatosFM, Nombre, Validacion

CRITICAL_FIELDS = ("nombre", "fecha_nacimiento", "sexo", "curp", "nue", "numero_documento")
RESIDENTE = ("RESIDENTE TEMPORAL", "RESIDENTE PERMANENTE")


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def split_printed_name(printed: str | None) -> tuple[str | None, str | None]:
    """'PEREZ LOPEZ Ana Maria' -> ('PEREZ LOPEZ', 'ANA MARIA'): apellidos en MAYÚSCULAS, nombres
    con inicial mayúscula. Si todo viene en mayúsculas no se puede separar."""
    if not printed:
        return None, None
    words = printed.split()

    def is_upper(w: str) -> bool:
        letters = [c for c in w if c.isalpha()]
        return bool(letters) and all(c.isupper() for c in letters)

    upper = [w for w in words if is_upper(w)]
    if len(upper) == len(words) or not upper:
        return None, None
    i = 0
    while i < len(words) and is_upper(words[i]):
        i += 1
    return " ".join(words[:i]).upper(), " ".join(words[i:]).upper()


class Merger:
    def __init__(self, vlm_front: dict | None, vlm_back: dict | None, ocr_front: FrontOcr, ocr_back: FrontOcr,
                 mrz: MrzResult | None) -> None:
        self.vf = vlm_front or {}
        self.vb = vlm_back or {}
        self.of = ocr_front
        self.ob = ocr_back
        self.mrz = mrz
        self.datos = DatosFM()
        self.conf: dict[str, Confianza] = {}
        self.checks: list[Validacion] = []
        self.warnings: list[str] = []

    # ------------------------------------------------------------ utilidades

    def _check(self, regla: str, ok: bool | None, detalle: str | None = None) -> None:
        resultado = "no_aplica" if ok is None else ("ok" if ok else "falla")
        self.checks = [c for c in self.checks if c.regla != regla]
        self.checks.append(Validacion(regla=regla, resultado=resultado, detalle=detalle))

    def _v(self, key: str, src: dict | None = None) -> str | None:
        val = (src if src is not None else self.vf).get(key)
        if isinstance(val, str):
            val = val.strip()
            return val or None
        return val

    def _mrz_ok(self, regla: str) -> bool:
        return bool(self.mrz) and any(c.nombre == regla and c.valido for c in self.mrz.checks)

    # ------------------------------------------------------------ campos

    def run(self) -> DatosFM:
        d = self.datos
        self._tipo()
        self._nue()
        self._nombre()
        self._fecha_nacimiento()
        self._sexo()
        self._curp()
        self._nacionalidad()
        self._fechas_vigencia()
        self._reverso()
        d.permiso_para_trabajar = bool(self.vf.get("permiso_para_trabajar")) or self.of.permiso_para_trabajar
        if self.mrz:
            d.mrz = list(self.mrz.lineas)
            d.mrz_nacionalidad = self.mrz.nacionalidad
        return d

    def _tipo(self) -> None:
        vlm = v.norm_text(self._v("tipo_documento"))
        vlm = re.sub(r"\s+", " ", vlm).strip() or None
        if vlm:
            for t in RESIDENTE:
                if t.replace(" ", "") in vlm.replace(" ", ""):
                    vlm = t
        ocr = self.of.tipo_documento
        val = vlm or ocr
        self.datos.tipo_documento = val
        if vlm and ocr:
            self._check("tipo_documento_vlm_vs_ocr", vlm == ocr, f"{vlm} vs {ocr}")
            self.conf["tipo_documento"] = "alta" if vlm == ocr else "baja"
        elif val:
            self.conf["tipo_documento"] = "media"
        else:
            self.conf["tipo_documento"] = "baja"

    def _nue(self) -> None:
        vlm = re.sub(r"\D", "", self._v("nue") or "")
        ocr = self.of.nue
        cands = [c for c in (vlm, ocr) if c and v.NUE_RE.match(c)]
        val = cands[0] if cands else (vlm or None)
        self.datos.nue = val
        if vlm and ocr and v.NUE_RE.match(vlm) and v.NUE_RE.match(ocr):
            self._check("nue_vlm_vs_ocr", vlm == ocr, f"{vlm} vs {ocr}")
            self.conf["nue"] = "alta" if vlm == ocr else "baja"
        elif val and v.NUE_RE.match(val):
            self.conf["nue"] = "media"
        elif self.datos.tipo_documento in RESIDENTE or val:
            self.conf["nue"] = "baja"

    def _nombre(self) -> None:
        printed = self._v("nombre_completo")
        ap, no = self._v("apellidos"), self._v("nombres")
        # El texto impreso separa apellidos (MAYÚSCULAS) de nombres (Title case) de forma fiable;
        # los campos apellidos/nombres del VLM suelen perder el primer apellido.
        ap2, no2 = split_printed_name(printed)
        if ap2 and no2:
            ap, no = ap2, no2
        elif not ap or not no:
            ap, no = ap or ap2, no or no2
        m_ap = self.mrz.apellidos if self.mrz else None
        m_no = self.mrz.nombres if self.mrz else None
        n = Nombre(apellidos=v.norm_text(ap) or None, nombres=v.norm_text(no) or None,
                   nombre_completo=(printed or " ".join(x for x in (ap, no) if x) or None))
        # Comparación con el renglón 3 de la MRZ (sin acentos, truncado a 30 caracteres)
        full_front = (v.norm_text(n.apellidos) + " " + v.norm_text(n.nombres)).strip() if (n.apellidos or n.nombres) else ""
        full_mrz = ((m_ap or "") + " " + (m_no or "")).strip()
        if full_front and full_mrz:
            a, b = full_front.replace(" ", ""), full_mrz.replace(" ", "")
            prefix_ok = a.startswith(b[:28]) or b.startswith(a[:28])
            overlap = v.word_overlap(full_front, full_mrz)
            ok = (prefix_ok or overlap >= 0.75 or v.similarity(full_front, full_mrz) >= 0.85
                  or v.names_match(full_front, full_mrz))
            self._check("nombre_vs_mrz", ok, f"'{full_front}' vs MRZ '{full_mrz}' (similitud {v.similarity(full_front, full_mrz):.2f})")
            if ok:
                self.conf["nombre"] = "alta"
                # El frente separa apellidos de nombres por mayúsculas; si no se pudo, la MRZ sí lo sabe.
                if not n.apellidos or not n.nombres:
                    n.apellidos, n.nombres = m_ap, m_no
            else:
                self.conf["nombre"] = "baja"
        elif full_front:
            self.conf["nombre"] = "media"
        elif full_mrz:
            n.apellidos, n.nombres, n.nombre_completo = m_ap, m_no, full_mrz
            self.conf["nombre"] = "media" if self.mrz and self.mrz.n_validos >= 2 else "baja"
            self.warnings.append("Nombre tomado de la MRZ (el anverso no se leyó)")
        else:
            self.conf["nombre"] = "baja"
        if not n.apellidos and not n.nombres and n.nombre_completo:
            n.apellidos = v.norm_text(n.nombre_completo)
        self.datos.nombre = n

    def _fecha_nacimiento(self) -> None:
        vlm = v.parse_date(self._v("fecha_nacimiento"))
        mrz = self.mrz.fecha_nacimiento if self.mrz else None
        mrz_ok = self._mrz_ok("mrz_fecha_nacimiento")
        curp = v.normalize_curp(self._v("curp"))
        curp_d = v.curp_birthdate(curp) if curp and len(curp) == 18 else None
        ocr = [v.parse_date(x) for x in self.of.fechas]
        sources = {"vlm": vlm, "mrz": mrz if mrz_ok else None, "curp": curp_d}
        vals = {k: x for k, x in sources.items() if x}
        mrz_corregida = bool(self.mrz) and any(c.nombre == "mrz_fecha_nacimiento" and c.corregido for c in self.mrz.checks)
        if mrz_ok and mrz and vlm and vlm != mrz and curp_d == vlm and v.curp_valid(curp or "") and mrz_corregida:
            # La MRZ se "reparó" con el dígito verificador hacia una fecha que ni el anverso ni la CURP
            # (con su propio verificador) respaldan: ganan las dos fuentes que coinciden.
            val = vlm
            self.conf["fecha_nacimiento"] = "alta"
            self._check("fecha_nacimiento_vs_mrz", False, f"anverso y CURP {vlm} vs MRZ reparada {mrz}; se entrega {vlm}")
            self.warnings.append("Fecha de nacimiento: la MRZ reparada difiere del anverso y la CURP; se usan estos")
        elif mrz_ok and mrz:
            val = mrz
            self.conf["fecha_nacimiento"] = "alta"
            if vlm and vlm != mrz:
                self._check("fecha_nacimiento_vs_mrz", False, f"anverso {vlm} vs MRZ {mrz}")
            elif vlm:
                self._check("fecha_nacimiento_vs_mrz", True)
        elif vlm:
            val = vlm
            agree = (curp_d == vlm) or (vlm in ocr) or (mrz == vlm)
            self.conf["fecha_nacimiento"] = "alta" if agree else "media"
            if mrz and mrz != vlm:
                self._check("fecha_nacimiento_vs_mrz", False, f"anverso {vlm} vs MRZ {mrz} (MRZ sin dígito válido)")
        elif vals:
            val = next(iter(vals.values()))
            self.conf["fecha_nacimiento"] = "media"
        else:
            val = None
            self.conf["fecha_nacimiento"] = "baja"
        distinct = set(vals.values())
        if len(distinct) > 1:
            self._check("fecha_nacimiento_consistente", False, "difieren: " + ", ".join(k for k in vals))
        elif vals:
            self._check("fecha_nacimiento_consistente", True)
        self.datos.fecha_nacimiento = _iso(val)

    def _sexo(self) -> None:
        printed = self._v("sexo")
        vlm = v.normalize_sex(printed)
        if printed and v.norm_text(printed) == "M":
            vlm = None  # "M" solo es ambiguo (hombre en MRZ, mujer en español)
        mrz = self.mrz.sexo if self.mrz else None
        curp = v.normalize_curp(self._v("curp"))
        curp_s = v.curp_sex(curp) if curp else None
        vals = {k: x for k, x in (("vlm", vlm), ("mrz", mrz), ("curp", curp_s)) if x}
        distinct = set(vals.values())
        if len(distinct) == 1 and len(vals) >= 2:
            self.conf["sexo"] = "alta"
            self._check("sexo_consistente", True)
        elif len(distinct) == 1:
            self.conf["sexo"] = "media"
        elif distinct:
            self.conf["sexo"] = "baja"
            self._check("sexo_consistente", False, "difieren: " + ", ".join(f"{k}={x}" for k, x in vals.items()))
        else:
            self.conf["sexo"] = "baja"
        # Prioridad: MRZ (si cuadra con alguien) > impreso > CURP
        val = None
        if mrz and (mrz == vlm or mrz == curp_s or not vals.keys() - {"mrz"}):
            val = mrz
        else:
            val = vlm or mrz or curp_s
        self.datos.sexo = val

    def _curp(self) -> None:
        vlm = v.normalize_curp(self._v("curp"))
        ocr = self.of.curp
        cands = [c for c in (vlm, ocr) if c]
        valid = [c for c in cands if v.curp_valid(c)]
        val = valid[0] if valid else (vlm or ocr)
        if not valid and val and len(val) == 18 and self.mrz:
            fixed = self._repair_curp(val)
            if fixed:
                self.warnings.append("CURP corregida con la fecha de nacimiento y sexo de la MRZ")
                val, valid = fixed, [fixed]
        self.datos.curp = val
        if not val:
            self.conf["curp"] = "baja"
            self._check("curp_estructura_y_digito", None)
            return
        ok = v.curp_valid(val)
        self._check("curp_estructura_y_digito", ok, val if not ok else None)
        if vlm and ocr:
            self._check("curp_vlm_vs_ocr", vlm == ocr, f"{vlm} vs {ocr}")
        self.conf["curp"] = "alta" if ok else "baja"
        if ok:
            bd = v.curp_birthdate(val)
            fn = v.parse_date(self.datos.fecha_nacimiento)
            if fn:
                self._check("curp_vs_fecha_nacimiento", bd == fn, f"CURP {bd} vs {fn}")
            if self.datos.sexo:
                self._check("curp_vs_sexo", v.curp_sex(val) == self.datos.sexo, f"CURP {v.curp_sex(val)} vs {self.datos.sexo}")
            self._check("curp_es_extranjero", val[11:13] == "NE", f"entidad {val[11:13]}")
            n = self.datos.nombre
            if n.apellidos and n.nombres:
                parts = n.apellidos.split()
                prefix = v.curp_name_prefix(parts[0], " ".join(parts[1:]) or None, n.nombres)
                alt = v.curp_name_prefix(parts[0], None, n.nombres)
                if prefix:
                    ok_name = val[:4] in (prefix, alt)
                    self._check("curp_vs_nombre", ok_name, f"CURP {val[:4]} vs esperado {prefix}")
                    if ok_name:
                        self.conf["nombre"] = "alta" if self.conf.get("nombre") != "baja" else "baja"

    def _repair_curp(self, curp: str) -> str | None:
        m = self.mrz
        if not (m and m.fecha_nacimiento and self._mrz_ok("mrz_fecha_nacimiento")):
            return None
        s = list(curp)
        s[4:10] = list(m.fecha_nacimiento.strftime("%y%m%d"))
        if m.sexo in ("H", "M"):
            s[10] = m.sexo
        cand = "".join(s)
        if v.curp_valid(cand):
            return cand
        # dígito verificador mal leído
        cand = cand[:17] + v.curp_check_digit(cand[:17])
        return cand if v.curp_valid(cand) else None

    def _nacionalidad(self) -> None:
        gent = v.norm_text(self._v("nacionalidad")) or None
        pais = (v.norm_text(self._v("pais")) or self.of.pais or "").strip() or None
        if pais and not re.fullmatch(r"[A-Z]{3}", pais):
            pais = v.nationality_iso(pais)
        mrz = self.mrz.nacionalidad if self.mrz else None
        iso_gent = v.nationality_iso(gent)
        self.datos.nacionalidad = gent
        cands = [c for c in (pais, mrz, iso_gent) if c]
        if pais and mrz:
            self._check("pais_vs_mrz", pais == mrz, f"{pais} vs MRZ {mrz}")
            self.conf["pais"] = "alta" if pais == mrz else "baja"
            self.datos.pais = mrz if (pais != mrz and iso_gent == mrz) else pais
        elif cands:
            self.datos.pais = cands[0]
            self.conf["pais"] = "alta" if len(set(cands)) == 1 and len(cands) >= 2 else "media"
        else:
            self.conf["pais"] = "baja"
        if gent:
            self.conf["nacionalidad"] = "alta" if iso_gent and iso_gent == (self.datos.pais or mrz) else "media"

    def _fechas_vigencia(self) -> None:
        exp = v.parse_date(self._v("fecha_expedicion"))
        venc = v.parse_date(self._v("fecha_vencimiento"))
        ocr = [v.parse_date(x) for x in self.of.fechas]
        mrz_d = self.mrz.fecha_expedicion if self.mrz else None
        mrz_ok = self._mrz_ok("mrz_fecha_expedicion")
        permanente = (self.datos.tipo_documento == "RESIDENTE PERMANENTE") or bool(self.mrz and self.mrz.sin_fecha)
        # Expedición: el INM la codifica en la MRZ (posición del "vencimiento" de ICAO)
        if mrz_ok and mrz_d and (exp is None or exp == mrz_d or (venc != mrz_d)):
            self.datos.fecha_expedicion = _iso(mrz_d)
            self.conf["fecha_expedicion"] = "alta"
            if exp and exp != mrz_d:
                self._check("fecha_expedicion_vs_mrz", False, f"anverso {exp} vs MRZ {mrz_d}")
            elif exp:
                self._check("fecha_expedicion_vs_mrz", True)
        elif exp:
            self.datos.fecha_expedicion = _iso(exp)
            self.conf["fecha_expedicion"] = "alta" if exp in ocr else "media"
        # Vencimiento: sólo impreso en el anverso (no tiene dígito verificador)
        e = v.parse_date(self.datos.fecha_expedicion)
        if venc and e and venc <= e and (mrz_ok or exp == e):
            # El vencimiento nunca es anterior a la expedición (respaldada por la MRZ): lectura errónea
            self.datos.fecha_vencimiento = _iso(venc)
            self.conf["fecha_vencimiento"] = "baja"
            self._check("expedicion_antes_de_vencimiento", False, f"{e} vs {venc}")
        elif venc:
            self.datos.fecha_vencimiento = _iso(venc)
            agree = venc in ocr or (mrz_ok and venc == mrz_d)
            self.conf["fecha_vencimiento"] = "alta" if agree else "media"
        elif permanente:
            # La tarjeta de Residente Permanente imprime la etiqueta de vencimiento sin valor
            self.conf["fecha_vencimiento"] = "alta" if self.datos.tipo_documento == "RESIDENTE PERMANENTE" else "media"
        elif self.datos.tipo_documento in ("RESIDENTE TEMPORAL", "VISITANTE"):
            self.conf["fecha_vencimiento"] = "baja"
        w = v.parse_date(self.datos.fecha_vencimiento)
        if e and w and self.conf.get("fecha_vencimiento") != "baja":
            self._check("expedicion_antes_de_vencimiento", e < w, f"{e} vs {w}")
        if w:
            self.datos.vigente = w >= date.today()
        elif permanente:
            self.datos.vigente = True

    def _reverso(self) -> None:
        d = self.datos
        mrz_num = self.mrz.numero_documento if self.mrz else None
        mrz_ok = self._mrz_ok("mrz_numero")
        vlm_num = re.sub(r"\D", "", self._v("numero_documento", self.vb) or "") or None
        if vlm_num and not 7 <= len(vlm_num) <= 9:
            vlm_num = None
        ocr_num = self.ob.numero_documento
        if mrz_num and mrz_ok:
            d.numero_documento = mrz_num
            self.conf["numero_documento"] = "alta"
            other = vlm_num or ocr_num
            if other:
                self._check("numero_documento_vs_mrz", other == mrz_num, f"reverso {other} vs MRZ {mrz_num}")
        elif vlm_num or ocr_num or mrz_num:
            cands = [c for c in (vlm_num, ocr_num, mrz_num) if c]
            d.numero_documento = cands[0]
            self.conf["numero_documento"] = "alta" if len(cands) >= 2 and len(set(cands)) == 1 else "media"
            if len(set(cands)) > 1:
                self.conf["numero_documento"] = "baja"
                self._check("numero_documento_consistente", False, " vs ".join(cands))
        elif self.mrz is not None or self.vb:
            self.conf["numero_documento"] = "baja"
        seg_v = self._v("numero_segob_inm", self.vb)
        seg_v = ("SEGOB-INM-" + re.sub(r"\D", "", seg_v)) if seg_v and re.search(r"\d{6,}", seg_v) else None
        seg_o = self.ob.numero_segob_inm or self.of.numero_segob_inm
        seg = seg_v or seg_o
        if seg:
            d.numero_segob_inm = seg
            self.conf["numero_segob_inm"] = "alta" if (seg_v and seg_o and seg_v == seg_o) else "media"
            if seg_v and seg_o and seg_v != seg_o:
                self.conf["numero_segob_inm"] = "baja"
        d.impreso_en = self._v("impreso_en", self.vb)
        d.condicion_estancia = self._v("condicion_estancia", self.vb)
        if self.mrz:
            for c in self.mrz.checks:
                self._check(c.nombre, c.valido, "corregido con el dígito verificador" if c.corregido else None)


def needs_review(conf: dict[str, Confianza]) -> list[str]:
    return [f for f, c in conf.items() if c == "baja"]
