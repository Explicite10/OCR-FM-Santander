"""Pruebas de validadores y fusión. Todos los datos son ficticios (dígitos verificadores calculados)."""
from datetime import date

from app import mrz_td1
from app import validators as v
from app.front_ocr import FrontOcr
from app.merge import Merger, split_printed_name

CURP = "PELA900315MNERPN00"


def test_curp_extranjero():
    assert v.curp_valid(CURP)
    assert v.curp_birthdate(CURP) == date(1990, 3, 15)
    assert v.curp_sex(CURP) == "M"
    assert not v.curp_valid("PELA900315MNERPN01")


def test_split_name():
    assert split_printed_name("PEREZ LOPEZ Ana Maria") == ("PEREZ LOPEZ", "ANA MARIA")
    assert split_printed_name("GARCIA JOSE LUIS") == (None, None)


def test_sex_and_dates():
    assert v.normalize_sex("Mujer") == "M" and v.normalize_sex("Hombre") == "H"
    assert v.parse_date("15/03/1990") == date(1990, 3, 15)
    assert v.nationality_iso("Española") == "ESP"


def test_merge_basic():
    mrz = mrz_td1.parse(["I<MEX12345678<8<<<<<<<<<<<<<<<", "9003152F2501109ESP<<<<<<<<<<<6", "PEREZ<LOPEZ<<ANA<MARIA<<<<<<<<"])
    vf = {"tipo_documento": "RESIDENTE TEMPORAL", "nue": "0000001234567", "nombre_completo": "PEREZ LOPEZ Ana Maria",
          "apellidos": "", "nombres": "", "nacionalidad": "Española", "pais": "ESP", "sexo": "Mujer",
          "fecha_nacimiento": "15/03/1990", "curp": "PELA900315MNERPNO0", "permiso_para_trabajar": True,
          "fecha_expedicion": "10/01/2025", "fecha_vencimiento": "09/01/2027"}
    vb = {"numero_segob_inm": "SEGOB-INM-00123456", "impreso_en": "OR CIUDAD DE MEXICO, 05/01/2025",
          "numero_documento": "12345678", "condicion_estancia": ""}
    of = FrontOcr(tipo_documento="RESIDENTE TEMPORAL", nue="0000001234567", curp=CURP,
                  fechas=["1990-03-15", "2025-01-10", "2027-01-09"])
    mg = Merger(vf, vb, of, FrontOcr(numero_segob_inm="SEGOB-INM-00123456", numero_documento="12345678"), mrz)
    d = mg.run()
    assert d.curp == CURP and mg.conf["curp"] == "alta"
    assert d.nombre.apellidos == "PEREZ LOPEZ" and d.nombre.nombres == "ANA MARIA" and mg.conf["nombre"] == "alta"
    assert d.sexo == "M" and mg.conf["sexo"] == "alta"
    assert d.fecha_nacimiento == "1990-03-15" and mg.conf["fecha_nacimiento"] == "alta"
    assert d.nue == "0000001234567" and mg.conf["nue"] == "alta"
    assert d.numero_documento == "12345678" and mg.conf["numero_documento"] == "alta"
    assert d.pais == "ESP" and mg.conf["pais"] == "alta"
    assert d.fecha_expedicion == "2025-01-10" and mg.conf["fecha_expedicion"] == "alta"
    assert d.fecha_vencimiento == "2027-01-09" and mg.conf["fecha_vencimiento"] == "alta"
    assert any(c.regla == "fecha_expedicion_vs_mrz" and c.resultado == "ok" for c in mg.checks)
    assert not [f for f in mg.conf if mg.conf[f] == "baja"], mg.conf


def test_nue_plausible_y_fecha_expedicion_ocr():
    """Datos ficticios. Permanente antigua: MRZ sin fecha, el VLM no lee la expedición y el OCR trae
    nacimiento + una fecha más."""
    from app.merge import NUE_PLAUSIBLE
    assert NUE_PLAUSIBLE.match("0000001234567") and not NUE_PLAUSIBLE.match("0000091234567")
    mrz = mrz_td1.parse(["I<MEX12345678<8<<<<<<<<<<<<<<<", "9003152F<<<<<<0ESP<<<<<<<<<<<6", "PEREZ<LOPEZ<<ANA<MARIA<<<<<<<<"])
    vf = {"tipo_documento": "RESIDENTE PERMANENTE", "nue": "0000001234567", "nombre_completo": "PEREZ LOPEZ Ana Maria",
          "nacionalidad": "Española", "pais": "ESP", "sexo": "Mujer", "fecha_nacimiento": "15/03/1990", "curp": "",
          "fecha_expedicion": "", "fecha_vencimiento": "", "permiso_para_trabajar": False}
    of = FrontOcr(tipo_documento="RESIDENTE PERMANENTE", nue="0000001234567", fechas=["1990-03-15", "2014-01-31"])
    d = Merger(vf, None, of, FrontOcr(), mrz).run()
    assert d.fecha_expedicion == "2014-01-31"
