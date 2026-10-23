"""Pruebas de la MRZ TD1. Todos los datos son ficticios (dígitos verificadores calculados)."""
from datetime import date

from app import mrz_td1 as m

L1 = "I<MEX12345678<8<<<<<<<<<<<<<<<"
L2 = "9003152F2501109ESP<<<<<<<<<<<6"
L3 = "PEREZ<LOPEZ<<ANA<MARIA<<<<<<<<"


def test_check_digit():
    assert m.check_digit("12345678<") == 8
    assert m.check_digit("900315") == 2
    assert m.check_digit("250110") == 9


def test_parse_valid():
    r = m.parse([L1, L2, L3])
    assert r is not None
    assert r.numero_documento == "12345678"
    assert r.fecha_nacimiento == date(1990, 3, 15)
    assert r.sexo == "M" and r.sexo_mrz == "F"
    assert r.fecha_expedicion == date(2025, 1, 10)
    assert r.nacionalidad == "ESP"
    assert r.apellidos == "PEREZ LOPEZ" and r.nombres == "ANA MARIA"
    assert r.valido, [c for c in r.checks]


def test_repair_ocr_confusions():
    # O/0, 1/I y espacios: se corrigen por el tipo de cada posición
    r = m.parse(["1<MEX1234567 8<8<<<<<<<<<<<<<<<", "9OO3152F25O1109ESP<<<<<<<<<<<6", "PER EZ<LOP EZ<<AN A<MARIA<<<<<"])
    assert r is not None and r.numero_documento == "12345678" and r.fecha_nacimiento == date(1990, 3, 15)
    assert r.valido, r.checks
    assert r.apellidos == "PEREZ LOPEZ"


def test_number_ambiguous_stays_invalid():
    # un dígito cambiado en el número admite varias reparaciones (el compuesto no distingue): no se adivina
    r = m.parse(["I<MEX12345673<8<<<<<<<<<<<<<<<", L2, L3])
    assert r is not None and not any(c.nombre == "mrz_numero" and c.valido for c in r.checks)


def test_permanente_sin_fecha():
    l1 = "I<MEX11223344<8<<<<<<<<<<<<<<<"
    l2 = "7005015F<<<<<<<KOR<<<<<<<<<<<2"
    r = m.parse([l1, l2, "KIM<<MINJI<<<<<<<<<<<<<<<<<<<<"])
    assert r is not None and r.sin_fecha and r.fecha_expedicion is None
    assert r.fecha_nacimiento == date(1970, 5, 1) and r.nacionalidad == "KOR"
    assert r.valido, r.checks


def test_find_mrz_lines():
    texts = ["SEGOB-INM-00123456", "No. 12345678", L1, L2, L3, "Santander"]
    assert m.find_mrz_lines(texts) == [L1, L2, L3]
    assert m.find_mrz_lines(["IDMEX1234567890<<1234567890123", "x", "y"]) is None
