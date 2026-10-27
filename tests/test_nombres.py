"""Reglas de nombres. Todos los nombres son ficticios."""
from app import validators as v
from app.merge import split_printed_name


def test_altisonantes():
    assert v.curp_name_prefix("CASAS", "GARCIA", "ANDRES") == "CXGA"
    assert v.curp_name_prefix("JONES", None, "SAMUEL") == "JOXS"
    assert v.curp_name_prefix("LI", None, "MEI-LING, ANNE") == "LIXM"


def test_split_printed_keeps_first_surname():
    assert split_printed_name("ROJAS HERRERA Carlos Andres") == ("ROJAS HERRERA", "CARLOS ANDRES")
    assert split_printed_name("ÁLVAREZ JIMÉNEZ Pablo Jorge Andrés") == ("ÁLVAREZ JIMÉNEZ", "PABLO JORGE ANDRÉS")
    assert split_printed_name("LI Mei-Ling, Anne") == ("LI", "MEI-LING, ANNE")


def test_names_match_truncated_mrz():
    assert v.names_match("ALVAREZ JIMENEZ PABLO JORGE ANDRES", "ALVAREZ JIMEN PABLO JORGE")
    assert v.names_match("SOUZA LIMA JUNIOR RAFAEL", "SOUZA LIMA JUNIQR RA")
    assert v.names_match("RAMOS DIAZ ELLEN", "RAMOS DIAZ EILEN")
    assert v.names_match("VILLANUEVA SOTO JUNIOR ALEJANDRO", "VILLANUEVA JUNNIOR ALEJANDROT")
    assert not v.names_match("MORALES REYES LUIS JESUS ANTONIO", "SESENTTTER")
    assert not v.names_match("GARCIA LOPEZ JUAN", "PEREZ RUIZ JUAN")


def test_titulo_visitante_sin_fuzzy():
    """Basura del OCR de un pasaporte ("ais inte") no debe pasar por el título VISITANTE."""
    from app.layout import is_title
    assert is_title("ais  inte") is None
    assert is_title("VISITANTE") == "VISITANTE"
    assert is_title("RESIDENTE PERMANENTE") == "RESIDENTE PERMANENTE"


def test_anverso_fuerte_gana_al_debil():
    """Pasaporte en la página 1 y tarjeta en la 2: el anverso debe ser la página 2."""
    from app.layout import front_strength
    from app.ocr import Line
    pasaporte = [Line("PASAPORTE N°", 0.9, 10, 10, 200, 30),
                 Line("P<VENNAVA<ROMERO<<YUNEIXI<KARINA<<<<<<<<<<<<", 0.9, 10, 40, 600, 60)]
    tarjeta = [Line("INSTITUTO NACIONAL DE MIGRACION", 0.9, 10, 10, 400, 30),
               Line("RESIDENTE PERMANENTE", 0.9, 10, 40, 300, 60)]
    assert front_strength("VISITANTE", pasaporte) == 0
    assert front_strength(None, tarjeta) == 1
    assert front_strength("RESIDENTE PERMANENTE", tarjeta) == 2


def test_impreso_en_desde_ocr():
    from app.front_ocr import extract
    from app.ocr import Line
    r = extract([Line("SEGOB-INM-00896574", 0.9, 0, 0, 300, 20), Line("Impreso en: SRF CHETUMAL, 14/01/2025", 0.9, 0, 30, 400, 50)])
    assert r.numero_segob_inm == "SEGOB-INM-00896574" and r.impreso_en == "SRF CHETUMAL, 14/01/2025"
    r = extract([Line("Impreso en:", 0.9, 0, 0, 100, 20), Line("OR CIUDAD DE MEXICO, 05/01/2025", 0.9, 0, 30, 400, 50)])
    assert r.impreso_en == "OR CIUDAD DE MEXICO, 05/01/2025"
