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
