"""Plan de atención (sección Forma Migratoria): las 8 validaciones y el bloque `validacion_plan`.
Datos ficticios. Mismos escenarios que docs/ejemplos_respuesta.json de OCR-INM-DocumentAI."""
from datetime import date

from app import plan, respuesta
from app.schemas import DatosFM, Meta, Nombre, ResultadoFM

IDS = ["hoja_en_blanco", "imagen_ilegible", "es_forma_migratoria", "vigente", "nombre_coincide",
       "curp_coincide", "fecha_nacimiento_coincide", "nacionalidad_coincide"]

DATOS = {"tipo_documento": "RESIDENTE TEMPORAL", "nue": "0000001234567", "apellidos": "PEREZ GOMEZ",
         "nombres": "MARIA FERNANDA", "nombre_completo": "PEREZ GOMEZ MARIA FERNANDA", "nacionalidad": "COLOMBIANA",
         "pais": "COL", "sexo": "M", "fecha_nacimiento": "1990-06-09", "curp": "PEGM900609MNERMR05",
         "fecha_expedicion": "2025-01-13", "fecha_vencimiento": f"{date.today().year + 1}-01-13",
         "numero_documento": "12345678"}
MRZ = {"lineas": ["x", "y", "z"], "digitos_control": {"numero_documento": True, "fecha_nacimiento": True}}


def _por_id(bloque: dict) -> dict:
    return {i["id"]: i for i in bloque["validaciones"]}


def test_cumple_todo():
    sol = plan.Solicitud(nombre="Maria Fernanda Perez Gomez", curp="pegm900609mnermr05",
                         fecha_nacimiento="09/06/1990", nacionalidad="Colombiana")
    b = plan.evaluar("forma_migratoria", DATOS, MRZ, sol)
    assert [i["id"] for i in b["validaciones"]] == IDS
    assert b["cumple"] is True and b["motivos_rechazo"] == []
    assert b["mensaje"] == plan.MENSAJE_OK
    assert all(i["resultado"] == ("SI" if i["id"] not in ("hoja_en_blanco", "imagen_ilegible") else "NO")
               for i in b["validaciones"])


def test_rechazo_con_motivos():
    sol = plan.Solicitud(apellido_paterno="Perez", nombres="Maria", fecha_nacimiento="1991-06-09",
                         nacionalidad="Venezolana")
    b = plan.evaluar("forma_migratoria", DATOS, MRZ, sol)
    r = _por_id(b)
    assert b["cumple"] is False and b["mensaje"] == plan.MENSAJE_RECHAZO
    assert r["nombre_coincide"]["resultado"] == "NO" and "FERNANDA GOMEZ" in r["nombre_coincide"]["detalle"]
    assert r["curp_coincide"]["resultado"] == "NO_APLICA" and r["curp_coincide"]["ok"]
    assert r["fecha_nacimiento_coincide"]["resultado"] == "NO"
    assert r["nacionalidad_coincide"]["resultado"] == "NO" and "VEN" in r["nacionalidad_coincide"]["detalle"]
    assert len(b["motivos_rechazo"]) == 3


def test_sin_solicitud_no_verificado():
    b = plan.evaluar("forma_migratoria", DATOS, MRZ, plan.Solicitud())
    r = _por_id(b)
    assert b["cumple"] is False
    assert r["nombre_coincide"]["resultado"] == "NO_VERIFICADO"
    assert r["curp_coincide"]["resultado"] == "NO_APLICA"
    assert any("No se enviaron datos de la solicitud" in m for m in b["motivos_rechazo"])


def test_curp_tolerante_a_confusiones_ocr():
    datos = dict(DATOS, curp="PEGM9O0609MNERMR05")  # O por 0 en la tarjeta
    b = plan.evaluar("forma_migratoria", datos, MRZ, plan.Solicitud(curp="PEGM900609MNERMR05"))
    assert _por_id(b)["curp_coincide"]["resultado"] == "SI"


def test_vigencia_por_anio_y_por_fecha():
    hoy = date(2026, 10, 27)
    vencida_este_anio = {"tipo_documento": "RESIDENTE TEMPORAL", "fecha_vencimiento": "2026-01-13"}
    assert plan.vigencia(vencida_este_anio, "anio", hoy)[0] is True   # mismo año: el plan la acepta
    assert plan.vigencia(vencida_este_anio, "fecha", hoy)[0] is False
    assert plan.vigencia({"tipo_documento": "RESIDENTE TEMPORAL", "fecha_vencimiento": "2025-12-31"}, "anio", hoy)[0] is False
    assert plan.vigencia({"tipo_documento": "RESIDENTE PERMANENTE"}, "anio", hoy)[0] is True
    assert plan.vigencia({"tipo_documento": "RESIDENTE TEMPORAL"}, "anio", hoy)[0] is None


def test_no_es_fm_y_hoja_en_blanco():
    b = plan.evaluar("otro", None, None, plan.Solicitud(nombre="X"))
    r = _por_id(b)
    assert r["es_forma_migratoria"]["resultado"] == "NO" and r["vigente"]["resultado"] == "NO_VERIFICADO"
    assert b["motivos_rechazo"] == ["¿Es una FM? NO: El documento no es una tarjeta de residente del INM."]
    b = plan.evaluar("hoja_en_blanco", None, None, plan.Solicitud())
    assert _por_id(b)["hoja_en_blanco"]["resultado"] == "SI" and len(b["motivos_rechazo"]) == 3


def test_ilegible_si_faltan_datos_esenciales():
    b = plan.evaluar("forma_migratoria", {"tipo_documento": "RESIDENTE TEMPORAL"}, {"error": "sin MRZ"},
                     plan.Solicitud(nombre="X"))
    assert _por_id(b)["imagen_ilegible"]["resultado"] == "SI"


def test_pais_iso3():
    assert plan.pais_iso3("Colombiana") == "COL" and plan.pais_iso3("colombia") == "COL"
    assert plan.pais_iso3("COL") == "COL" and plan.pais_iso3("CO") == "COL"
    assert plan.pais_iso3("Estadounidense") == "USA" and plan.pais_iso3("Marciana") is None


def test_respuesta_completa_con_validacion_plan():
    """construir + con_plan: el sobre homologado trae validacion_plan con las 8 preguntas en orden."""
    r = ResultadoFM(estado="ok", datos=DatosFM(tipo_documento="RESIDENTE TEMPORAL", nue="0000001234567",
                                                nombre=Nombre(apellidos="PEREZ GOMEZ", nombres="MARIA FERNANDA",
                                                              nombre_completo="PEREZ GOMEZ Maria Fernanda"),
                                                nacionalidad="COLOMBIANA", pais="COL", sexo="M",
                                                fecha_nacimiento="1990-06-09", curp="PEGM900609MNERMR05",
                                                fecha_vencimiento=DATOS["fecha_vencimiento"], numero_documento="12345678"),
                    meta=Meta(tiempo_total_ms=1, paginas=2, pagina_anverso=2, pagina_reverso=2, categoria="forma_migratoria"))
    body = respuesta.con_plan(respuesta.construir(r), plan.Solicitud(nombre="Maria Fernanda Perez Gomez",
                                                                    fecha_nacimiento="1990-06-09", nacionalidad="COL"))
    assert body["codigo"] in (200, 211, 212)
    assert body["datos"]["nombre_completo"] == "PEREZ GOMEZ MARIA FERNANDA"
    assert body["datos"]["vigente"] is True
    assert body["meta"]["paginas_forma_migratoria"] == [2] and body["meta"]["paginas_ignoradas"] == [1]
    vp = body["validacion_plan"]
    assert set(vp) == {"cumple", "mensaje", "motivos_rechazo", "regla_vigencia", "validaciones"}
    assert [i["id"] for i in vp["validaciones"]] == IDS
    assert vp["cumple"] is True


def test_rechazo_220_tambien_trae_validacion_plan():
    r = ResultadoFM(estado="rechazado", error="no es FM", meta=Meta(tiempo_total_ms=1, paginas=1, categoria="otro",
                                                                  documento_detectado="pasaporte"))
    body = respuesta.con_plan(respuesta.construir(r), plan.Solicitud())
    assert body["codigo"] == 220 and body["validacion_plan"]["cumple"] is False
    assert body["validacion_plan"]["motivos_rechazo"] == ["¿Es una FM? NO: El documento no es una tarjeta de residente del INM."]


def test_502_sin_validacion_plan():
    r = ResultadoFM(estado="error", error="VLM caído", error_codigo=502, meta=Meta(tiempo_total_ms=1))
    body = respuesta.con_plan(respuesta.construir(r), plan.Solicitud())
    assert body["codigo"] == 502 and body["estado"] == "ERROR_MODELO_VISION" and "validacion_plan" not in body
    assert respuesta.http_status(502) == 502
