"""Contract folios (RN-38). Every value here is synthetic."""

from __future__ import annotations

from datetime import date

import pytest
from django.core.exceptions import ValidationError

from crm_easyoffice.contratos.folio import formatear_folio
from crm_easyoffice.contratos.models import Contrato
from crm_easyoffice.contratos.models import CorrelativoFolio
from crm_easyoffice.contratos.services import LineaContrato
from crm_easyoffice.contratos.tests.factories import domicilio_en
from crm_easyoffice.contratos.tests.factories import marca
from crm_easyoffice.contratos.tests.factories import nuevo_contrato
from crm_easyoffice.contratos.tests.factories import servicio
from crm_easyoffice.inmuebles.tests.factories import OficinaFactory

pytestmark = pytest.mark.django_db


def test_folio_has_branch_correlative_and_year():
    contrato = nuevo_contrato()

    assert contrato.folio == "LF-0001-2026"
    assert (contrato.codigo_sucursal, contrato.correlativo, contrato.anio_folio) == (
        "LF",
        1,
        2026,
    )


def test_correlative_is_shared_across_branches():
    primero = nuevo_contrato(lineas=[domicilio_en("LF")])
    segundo = nuevo_contrato(lineas=[domicilio_en("VL")])
    tercero = nuevo_contrato(lineas=[domicilio_en("SA")])

    assert [primero.folio, segundo.folio, tercero.folio] == [
        "LF-0001-2026",
        "VL-0002-2026",
        "SA-0003-2026",
    ]


def test_correlative_is_shared_across_brands():
    easy = nuevo_contrato(marca=marca("EASY OFFICE"))
    inoffice = nuevo_contrato(marca=marca("INOFFICE"))

    assert (easy.correlativo, inoffice.correlativo) == (1, 2)


def test_correlative_restarts_each_year():
    nuevo_contrato(fecha_emision=date(2026, 12, 31))
    nuevo_contrato(fecha_emision=date(2026, 12, 31))

    enero = nuevo_contrato(fecha_emision=date(2027, 1, 2))

    assert enero.folio == "LF-0001-2027"
    assert CorrelativoFolio.objects.get(anio=2026).ultimo == 2  # noqa: PLR2004


def test_width_comes_from_settings(settings):
    settings.CONTRATO_FOLIO_ANCHO = 2

    assert nuevo_contrato().folio == "LF-01-2026"


def test_correlative_wider_than_width_is_not_truncated():
    CorrelativoFolio.objects.create(anio=2026, ultimo=9999)

    assert nuevo_contrato().folio == "LF-10000-2026"
    assert formatear_folio("VL", 12345, 2026, ancho=4) == "VL-12345-2026"


def test_branch_code_comes_from_first_located_service():
    contrato = nuevo_contrato(
        lineas=[
            LineaContrato(servicio=servicio("web-mail-dominio")),
            domicilio_en("VL"),
        ],
    )

    assert contrato.folio.startswith("VL-")


def test_explicit_branch_required_without_located_service():
    with pytest.raises(ValidationError) as error:
        nuevo_contrato(lineas=[LineaContrato(servicio=servicio("creacion-empresas"))])

    assert (
        error.value.error_dict["codigo_sucursal"][0].code == "sucursal_no_determinada"
    )


def test_explicit_branch_is_used_without_located_service():
    contrato = nuevo_contrato(
        lineas=[LineaContrato(servicio=servicio("creacion-empresas"))],
        codigo_sucursal="SA",
    )

    assert contrato.folio == "SA-0001-2026"


def test_explicit_branch_must_match_the_located_service():
    with pytest.raises(ValidationError) as error:
        nuevo_contrato(lineas=[domicilio_en("LF")], codigo_sucursal="VL")

    assert "codigo_sucursal" in error.value.message_dict


def test_unknown_explicit_branch_is_rejected():
    with pytest.raises(ValidationError):
        nuevo_contrato(
            lineas=[LineaContrato(servicio=servicio("creacion-empresas"))],
            codigo_sucursal="XX",
        )


def test_warehouse_contract_requires_explicit_branch():
    bodega = OficinaFactory.create(tipo="bodega")
    linea = LineaContrato(servicio=servicio(), inmueble=bodega)

    with pytest.raises(ValidationError):
        nuevo_contrato(lineas=[linea])

    assert nuevo_contrato(lineas=[linea], codigo_sucursal="VL").folio.startswith("VL-")


def test_failed_creation_does_not_consume_a_number():
    with pytest.raises(ValidationError):
        nuevo_contrato(duracion_meses=7)

    assert nuevo_contrato().correlativo == 1
    assert Contrato.objects.count() == 1


def test_rollback_after_numbering_releases_the_number(monkeypatch):
    # A failure inside the transaction, after the number was taken.
    def falla(*args, **kwargs):
        raise RuntimeError

    monkeypatch.setattr(
        "crm_easyoffice.contratos.services.ServicioContratado.objects.bulk_create",
        falla,
    )
    with pytest.raises(RuntimeError):
        nuevo_contrato()
    monkeypatch.undo()

    assert nuevo_contrato().correlativo == 1
