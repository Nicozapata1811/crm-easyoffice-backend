"""How terms print in the contracts."""

from __future__ import annotations

import pytest

from crm_easyoffice.documentos import formato


@pytest.mark.parametrize(
    ("meses", "texto"),
    [
        (1, "UN (1) MES"),
        (3, "TRES (3) MESES"),
        (4, "CUATRO (4) MESES"),
        (6, "SEIS (6) MESES"),
        (12, "DOCE (12) MESES"),
        (24, "VEINTICUATRO (24) MESES"),
        (36, "TREINTA Y SEIS (36) MESES"),
        (40, "CUARENTA (40) MESES"),
    ],
)
def test_the_term_in_words(meses, texto):
    assert formato.duracion_en_letras(meses) == texto


def test_the_term_in_figures_agrees_in_number():
    assert formato.duracion(12) == "(12 MESES)"
    assert formato.duracion(1) == "(1 MES)"


@pytest.mark.parametrize("meses", [0, 100])
def test_terms_out_of_range_are_refused(meses):
    with pytest.raises(ValueError, match="outside"):
        formato.en_letras(meses)
