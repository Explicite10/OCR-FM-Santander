"""Respuesta homologada de la API (mismo sobre que las APIs de INE y pasaporte).

    { codigo, estado, mensaje, datos, mrz, validacion, avisos, clasificacion, confianza, meta }

* `codigo` dice qué pasó y no cambia de significado; `mensaje` es sólo para mostrar.
* Si un dato no se pudo leer, la llave no aparece.
* 200 = todo cuadró · 210 = datos que se contradicen · 211 = algo pide ojo humano ·
  212 = quedaron comprobaciones sin correr · 22x = se evaluó pero no se extrajo.
"""

from . import mrz_td1
from . import validators as v
from .schemas import ResultadoFM

ESTADOS = {
    200: "PROCESADO",
    210: "PROCESADO_CON_DISCREPANCIAS",
    211: "PROCESADO_CON_AVISOS",
    212: "PROCESADO_INCOMPLETO",
    220: "NO_ES_FORMA_MIGRATORIA",
    221: "HOJA_EN_BLANCO",
    222: "ARCHIVO_CORRUPTO",
    223: "PDF_PROTEGIDO",
    224: "LIMITE_PAGINAS",
    400: "ARCHIVO_NO_SOPORTADO",
    401: "NO_AUTORIZADO",
    404: "NO_ENCONTRADO",
    405: "METODO_NO_PERMITIDO",
    413: "ARCHIVO_DEMASIADO_GRANDE",
    422: "PETICION_INVALIDA",
    500: "ERROR_INTERNO",
    503: "SERVICIO_NO_DISPONIBLE",
}

MENSAJES = {
    200: "El documento se procesó y todas las comprobaciones cuadraron.",
    210: "El documento se procesó, pero hay datos que se contradicen entre sí: revisa validacion.discrepancias.",
    211: "El documento se procesó sin contradicciones, pero hay puntos que conviene revisar a mano: revisa avisos.",
    212: "El documento se procesó, pero quedaron comprobaciones sin correr: revisa validacion.sin_verificar.",
    220: "El documento no trae una tarjeta de residente del INM (forma migratoria). No se extrajo ningún dato.",
    221: "El documento viene en blanco o ilegible: no se leyó ningún texto.",
    222: "El archivo está dañado, incompleto o no es del tipo que dice. Envíalo de nuevo.",
    223: "El PDF está protegido con contraseña. Quítasela y vuelve a enviarlo.",
    224: "El documento excede el máximo de páginas por llamada: envía sólo las de la tarjeta.",
    400: "Tipo de archivo no soportado.",
    401: "API key inválida o ausente (header X-API-Key).",
    404: "No existe.",
    405: "Método no permitido.",
    413: "El archivo excede el tamaño máximo permitido.",
    422: "La petición no es válida.",
    500: "Error interno. Repórtalo.",
    503: "El servicio no está disponible.",
}


def http_status(codigo: int) -> int:
    return 200 if codigo < 300 else codigo


def sobre(codigo: int, mensaje: str | None = None, **cuerpo) -> dict:
    out = {"codigo": codigo, "estado": ESTADOS.get(codigo, "DESCONOCIDO"), "mensaje": mensaje or MENSAJES.get(codigo, "")}
    out.update({k: v for k, v in cuerpo.items() if v is not None})
    return out


def _clean(d: dict, keep_none: tuple[str, ...] = ()) -> dict:
    return {k: v for k, v in d.items() if (v not in (None, "", [], {})) or k in keep_none}


def datos(r: ResultadoFM) -> dict:
    d = r.datos
    return _clean({
        "tipo_documento": d.tipo_documento,
        "nue": d.nue,
        "apellidos": d.nombre.apellidos,
        "nombres": d.nombre.nombres,
        "nombre_completo": d.nombre.nombre_completo,
        "nacionalidad": d.nacionalidad,
        "pais": d.pais,
        "sexo": d.sexo,
        "fecha_nacimiento": d.fecha_nacimiento,
        "curp": d.curp,
        "permiso_para_trabajar": d.permiso_para_trabajar,
        "fecha_expedicion": d.fecha_expedicion,
        "fecha_vencimiento": d.fecha_vencimiento,
        "vigente": d.vigente,
        "numero_documento": d.numero_documento,
        "numero_segob_inm": d.numero_segob_inm,
        "impreso_en": d.impreso_en,
        "condicion_estancia": d.condicion_estancia,
        "pais_emisor": "MEX" if (d.nue or d.numero_documento or d.tipo_documento) else None,
    })


def mrz(r: ResultadoFM) -> dict:
    lineas = r.datos.mrz
    if not lineas:
        return {"error": "No se localizó la MRZ del reverso"}
    m = mrz_td1.parse(lineas)
    if m is None or m.n_validos == 0 or not m.numero_documento:
        return {"error": "MRZ ilegible: ningún dígito de control cuadra", "texto_crudo": "\n".join(lineas)}
    checks = {c.nombre: c.valido for c in m.checks}
    out = _clean({
        "lineas": m.lineas,
        "tipo_documento": m.lineas[0][0:2],
        "pais_emisor": m.lineas[0][2:5],
        "numero_documento": m.numero_documento,
        "fecha_nacimiento": m.fecha_nacimiento.isoformat() if m.fecha_nacimiento else None,
        "sexo": m.sexo,
        "fecha_expedicion": m.fecha_expedicion.isoformat() if m.fecha_expedicion else None,
        "sin_fecha_expedicion": m.sin_fecha or None,
        "nacionalidad": m.nacionalidad,
        "apellidos": m.apellidos,
        "nombres": m.nombres,
    })
    out["digitos_control"] = {
        "numero_documento": checks.get("mrz_numero", False),
        "fecha_nacimiento": checks.get("mrz_fecha_nacimiento", False),
        "fecha_expedicion": checks.get("mrz_fecha_expedicion") if "mrz_fecha_expedicion" in checks else None,
        "compuesto": checks.get("mrz_compuesto", False),
    }
    out["integra"] = m.valido
    origen = {"ocr": "texto", "vlm": "entidad"}.get((r.meta.mrz_fuente if r.meta else None) or "")
    if origen:
        out["origen"] = origen
    return out


_MRZ_RULES = ("mrz_numero", "mrz_fecha_nacimiento", "mrz_fecha_expedicion", "mrz_compuesto")
_MRZ_LABEL = {"mrz_numero": "numero_documento", "mrz_fecha_nacimiento": "fecha_nacimiento",
              "mrz_fecha_expedicion": "fecha_expedicion", "mrz_compuesto": "compuesto"}
LABELS = {
    "nombre_vs_mrz": "apellidos y nombres (MRZ)",
    "fecha_nacimiento_vs_mrz": "fecha_nacimiento (anverso vs MRZ)",
    "fecha_expedicion_vs_mrz": "fecha_expedicion (anverso vs MRZ)",
    "numero_documento_vs_mrz": "numero_documento (reverso vs MRZ)",
    "numero_documento_consistente": "numero_documento",
    "fecha_nacimiento_consistente": "fecha_nacimiento (anverso, MRZ, CURP)",
    "sexo_consistente": "sexo (anverso, MRZ, CURP)",
    "curp_estructura_y_digito": "curp (estructura y dígito verificador)",
    "curp_vs_fecha_nacimiento": "curp vs fecha_nacimiento",
    "curp_vs_sexo": "curp vs sexo",
    "curp_vs_nombre": "curp vs nombre (iniciales)",
    "curp_es_extranjero": "curp (entidad NE = nacido en el extranjero)",
    "pais_vs_mrz": "pais vs nacionalidad (MRZ)",
    "expedicion_antes_de_vencimiento": "fecha_expedicion < fecha_vencimiento",
}
_INTERNAL = ("_vlm_vs_ocr",)
_SOFT = ("curp_es_extranjero", "curp_vs_nombre")  # fallas que son aviso, no contradicción


def validacion(r: ResultadoFM) -> dict:
    checks = r.validaciones
    coincidencias: list[str] = []
    discrepancias: list[str] = []
    sin_verificar: list[str] = []
    avisos_extra: list[str] = []

    mrz_checks = [c for c in checks if c.regla in _MRZ_RULES]
    mrz_integra = bool(mrz_checks) and all(c.resultado == "ok" for c in mrz_checks)
    if mrz_checks:
        if mrz_integra:
            coincidencias.append("MRZ (dígitos de control)")
        else:
            bad = [_MRZ_LABEL[c.regla] for c in mrz_checks if c.resultado != "ok"]
            if bad == ["compuesto"]:
                coincidencias.append("MRZ (dígitos de control de número y fechas)")
                avisos_extra.append("MRZ: el dígito compuesto no cuadra (suele quedar tapado por el sello); "
                                    "número y fechas sí cuadran con sus dígitos verificadores")
            else:
                discrepancias.append(f"MRZ (dígitos de control): no cuadran {', '.join(bad)}")
    else:
        sin_verificar.append("MRZ: no se localizó o no se pudo leer el reverso")

    by_rule = {c.regla: c for c in checks}
    # Número y fecha de nacimiento con dígito verificador válido: la MRZ respalda esos datos aunque el
    # dígito compuesto (a menudo tapado por el sello) no cuadre.
    mrz_core = all(by_rule.get(k) is not None and by_rule[k].resultado == "ok"
                   for k in ("mrz_numero", "mrz_fecha_nacimiento"))
    curp = r.datos.curp
    curp_bd = v.curp_birthdate(curp) if curp and v.curp_valid(curp) else None
    fn = v.parse_date(r.datos.fecha_nacimiento)
    for c in checks:
        regla = c.regla
        if regla in _MRZ_RULES or any(regla.endswith(s) for s in _INTERNAL):
            continue
        label = LABELS.get(regla, regla)
        detalle = f": {c.detalle}" if c.detalle else ""
        if c.resultado == "ok":
            coincidencias.append(label)
        elif c.resultado == "no_aplica":
            sin_verificar.append(f"{label}: falta el dato")
        elif regla in _SOFT:
            avisos_extra.append(f"{label}{detalle}")
        elif regla == "fecha_nacimiento_consistente" and mrz_core and fn and (curp_bd is None or curp_bd == fn):
            # Sólo difiere la lectura del anverso: la MRZ (dígito verificador) y, si es válida, la CURP
            # respaldan la fecha entregada. Es error de lectura, no contradicción del documento.
            avisos_extra.append(f"datos.fecha_nacimiento: el anverso se leyó distinto ({c.detalle}); se entrega la de "
                                "la MRZ, respaldada por su dígito verificador")
        elif regla.endswith("_vs_mrz") and (mrz_integra or mrz_core) and regla != "nombre_vs_mrz":
            # La MRZ íntegra respalda el dato entregado; lo que difiere es la lectura del anverso.
            avisos_extra.append(f"{label}{detalle}; se entrega el de la MRZ, respaldado por su dígito verificador")
        else:
            discrepancias.append(f"{label}{detalle}")

    if r.meta and "vlm_anverso" not in (r.meta.tiempos_ms or {}):
        sin_verificar.append("anverso: el modelo de visión no leyó el anverso; datos sólo del OCR")
    return {
        "ok": not discrepancias,
        "completo": not sin_verificar,
        "coincidencias": list(dict.fromkeys(coincidencias)),
        "discrepancias": discrepancias,
        "sin_verificar": sin_verificar,
        "_avisos": avisos_extra,
    }


_INFO = ("Localizador:", "El localizador no vio", "VLM deshabilitado")


def avisos(r: ResultadoFM) -> list[str]:
    out = [f"datos.{f}: confianza baja (las lecturas no coinciden o no se pudo leer); revisar contra el original"
           for f in r.campos_a_revisar]
    out += [w for w in r.advertencias if not w.startswith(_INFO)]
    return out


def construir(r: ResultadoFM) -> dict:
    meta = r.meta
    if r.estado == "error":
        base = MENSAJES.get(r.error_codigo or 222, "")
        return sobre(r.error_codigo or 222, f"{base} Detalle: {r.error}" if r.error else base)

    clasif = {
        "categoria": meta.categoria if meta else None,
        "confianza": None,
        "caracteres_leidos": meta.caracteres_leidos if meta else None,
        "senales": (meta.senales_fm if meta else None) or None,
        "otros_documentos": (meta.otros_documentos if meta else None) or None,
    }
    if r.estado == "rechazado":
        blanco = meta is not None and meta.categoria == "hoja_en_blanco"
        clasif.update(motivo=r.error, documento_detectado=meta.documento_detectado if meta else None)
        return sobre(221 if blanco else 220, clasificacion=_clean(clasif, keep_none=("categoria", "confianza")))

    val = validacion(r)
    avs = avisos(r) + val.pop("_avisos")
    if val["discrepancias"]:
        codigo = 210
    elif avs:
        codigo = 211
    elif val["sin_verificar"]:
        codigo = 212
    else:
        codigo = 200
    if codigo == 200 and r.estado == "revisar":
        codigo = 211
        avs.append("El documento requiere revisión humana")

    return sobre(
        codigo,
        id=r.id,
        datos=datos(r) or None,
        mrz=mrz(r),
        validacion=val,
        avisos=avs,
        clasificacion=_clean(clasif, keep_none=("categoria", "confianza")),
        confianza=r.confianza or None,
        meta=_clean({"tiempo_total_ms": meta.tiempo_total_ms, "tiempos_ms": meta.tiempos_ms,
                     "modelo_vlm": meta.modelo_vlm, "paginas": meta.paginas,
                     "pagina_anverso": meta.pagina_anverso, "pagina_reverso": meta.pagina_reverso,
                     "recorte_anverso": meta.recorte_anverso, "recorte_reverso": meta.recorte_reverso,
                     "mrz_fuente": meta.mrz_fuente}) if meta else None,
    )
