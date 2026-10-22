"""Who holds a property only one client may use (PLT-02 flag). Synthetic data."""

from __future__ import annotations

from datetime import date

import pytest

from crm_easyoffice.contratos.models import Contrato
from crm_easyoffice.contratos.services import LineaContrato
from crm_easyoffice.contratos.services import anular_borrador
from crm_easyoffice.contratos.services import inmuebles_ocupados
from crm_easyoffice.contratos.tests.factories import domicilio_en
from crm_easyoffice.contratos.tests.factories import nuevo_contrato
from crm_easyoffice.contratos.tests.factories import servicio
from crm_easyoffice.inmuebles.models import TipoInmueble
from crm_easyoffice.inmuebles.tests.factories import OficinaFactory
from crm_easyoffice.ventas.models import CicloPago

pytestmark = pytest.mark.django_db

# nuevo_contrato starts on 2026-10-02 for 12 months: it expires on 2027-10-01.
DENTRO = (date(2027, 1, 1), date(2027, 12, 31))
DESPUES = (date(2027, 10, 2), date(2028, 10, 1))


@pytest.fixture
def bodega():
    return OficinaFactory.create(tipo=TipoInmueble.BODEGA)


def con_bodega(bodega, **datos) -> Contrato:
    linea = LineaContrato(
        servicio=servicio("bodega"),
        inmueble=bodega,
        ciclo_pago=CicloPago.objects.get(codigo="anual"),
    )
    return nuevo_contrato(lineas=[domicilio_en("LF"), linea], **datos)


def ocupados(bodega, periodo, **extra) -> set[int]:
    return inmuebles_ocupados([bodega.pk], *periodo, **extra)


def test_an_overlapping_contract_holds_the_property(bodega):
    con_bodega(bodega, renovacion_automatica=False)

    assert ocupados(bodega, DENTRO) == {bodega.pk}
    assert ocupados(bodega, DESPUES) == set()


def test_an_auto_renewing_contract_holds_it_open_ended(bodega):
    con_bodega(bodega, renovacion_automatica=True)

    assert ocupados(bodega, DESPUES) == {bodega.pk}


def test_a_draft_holds_it_and_a_void_one_does_not(bodega):
    borrador = con_bodega(bodega, borrador=True)
    assert ocupados(bodega, DENTRO) == {bodega.pk}

    anular_borrador(borrador)
    assert ocupados(bodega, DENTRO) == set()


def test_a_terminated_contract_frees_it_from_its_end(bodega):
    contrato = con_bodega(bodega, renovacion_automatica=True)
    Contrato.objects.filter(pk=contrato.pk).update(terminado_en=date(2027, 3, 31))

    assert ocupados(bodega, (date(2027, 4, 1), date(2027, 6, 30))) == set()
    assert ocupados(bodega, (date(2027, 3, 1), date(2027, 6, 30))) == {bodega.pk}


def test_the_contract_being_edited_does_not_hold_it_against_itself(bodega):
    contrato = con_bodega(bodega, borrador=True)

    assert ocupados(bodega, DENTRO, excluir_contrato=contrato.pk) == set()


def test_a_later_contract_does_not_hold_an_earlier_period(bodega):
    con_bodega(bodega)

    assert ocupados(bodega, (date(2026, 1, 1), date(2026, 10, 1))) == set()
