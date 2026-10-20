"""Contracts in force, about to expire and expired (RF-14). All data is synthetic."""

from __future__ import annotations

from datetime import date
from datetime import timedelta
from typing import Any

import pytest

from crm_easyoffice.contratos.models import Contrato
from crm_easyoffice.contratos.services import resumen_vencimientos
from crm_easyoffice.contratos.tests.factories import nuevo_contrato

pytestmark = pytest.mark.django_db

REFERENCIA = date(2027, 3, 1)
DIAS_AVISO = 30
NINGUNO = {"activos": 0, "por_vencer": 0, "vencidos": 0}


def dias(n: int) -> date:
    return REFERENCIA + timedelta(days=n)


def que_vence(vencimiento: date, *, renueva: bool = False, **datos: Any) -> Contrato:
    """A contract started in October 2026 whose term ends on ``vencimiento``."""
    contrato = nuevo_contrato(renovacion_automatica=renueva, **datos)
    Contrato.objects.filter(pk=contrato.pk).update(fecha_vencimiento=vencimiento)
    contrato.refresh_from_db()
    return contrato


def resumen() -> dict[str, int]:
    return resumen_vencimientos(REFERENCIA, DIAS_AVISO)


def test_notice_window_is_inclusive_at_both_ends():
    que_vence(dias(0))
    que_vence(dias(DIAS_AVISO))
    que_vence(dias(DIAS_AVISO + 1))
    que_vence(dias(-1))

    assert resumen() == {"activos": 3, "por_vencer": 2, "vencidos": 1}


def test_an_automatically_renewing_contract_stays_in_force_after_its_term():
    que_vence(dias(-1), renueva=True)

    assert resumen() == {"activos": 1, "por_vencer": 0, "vencidos": 0}


def test_an_automatically_renewing_contract_is_due_in_its_first_term():
    que_vence(dias(10), renueva=True)

    assert resumen() == {"activos": 1, "por_vencer": 1, "vencidos": 0}


@pytest.mark.parametrize(
    "estado",
    [Contrato.Estado.BORRADOR, Contrato.Estado.TERMINADO, Contrato.Estado.ANULADO],
)
def test_drafts_terminated_and_annulled_contracts_never_count(estado):
    for vencimiento in (dias(10), dias(-10)):
        contrato = que_vence(vencimiento)
        Contrato.objects.filter(pk=contrato.pk).update(estado=estado)

    assert resumen() == NINGUNO


def test_a_contract_that_has_not_started_counts_nowhere():
    nuevo_contrato(fecha_inicio=dias(1), duracion_meses=1)

    assert resumen() == NINGUNO


def test_a_terminated_term_is_not_expired():
    que_vence(dias(-10))
    contrato = que_vence(dias(-10))
    Contrato.objects.filter(pk=contrato.pk).update(terminado_en=dias(-10))

    assert resumen() == {"activos": 0, "por_vencer": 0, "vencidos": 1}


def test_a_renewed_contract_is_neither_due_nor_expired():
    vencido = que_vence(dias(-1))
    por_vencer = que_vence(dias(5))
    for anterior in (vencido, por_vencer):
        renovacion = que_vence(dias(400))
        Contrato.objects.filter(pk=renovacion.pk).update(contrato_anterior=anterior)

    assert resumen() == {"activos": 3, "por_vencer": 0, "vencidos": 0}


def test_an_annulled_renewal_does_not_count_as_renewed():
    anterior = que_vence(dias(-1))
    renovacion = que_vence(dias(400))
    Contrato.objects.filter(pk=renovacion.pk).update(
        contrato_anterior=anterior,
        estado=Contrato.Estado.ANULADO,
    )

    assert resumen() == {"activos": 0, "por_vencer": 0, "vencidos": 1}
