"""Klap webhooks against the real adapter. All data here is synthetic."""

from __future__ import annotations

from http import HTTPStatus

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from crm_easyoffice.integrations.payment.klap import firma_webhook
from crm_easyoffice.ventas.models import EventoPago
from crm_easyoffice.ventas.models import OrdenPago
from crm_easyoffice.ventas.models import Venta
from crm_easyoffice.ventas.tests.factories import OrdenPagoFactory

API_KEY = "synthetic-api-key"

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _klap(settings):
    settings.PAYMENT_PROVIDER = "klap"
    settings.KLAP_API_KEY = API_KEY
    settings.KLAP_API_BASE_URL = "https://klap.invalid"


@pytest.fixture
def orden() -> OrdenPago:
    return OrdenPagoFactory.create()


def enviar(orden: OrdenPago, evento: str, *, firma: str | None = None, **extra):
    payload = {
        "order_id": orden.id_externo,
        "reference_id": str(orden.referencia),
        "amount": str(orden.monto),
        "mc_code": "MC-1",
        **extra,
    }
    firma = firma or firma_webhook(
        payload["reference_id"],
        payload["order_id"],
        API_KEY,
    )
    return APIClient(enforce_csrf_checks=True).post(
        reverse("pagos:webhook", args=["klap", evento]),
        payload,
        format="json",
        headers={"Apikey": firma},
    )


def test_confirmation_pays_the_sale(orden):
    response = enviar(orden, "confirmacion")

    orden.refresh_from_db()
    assert response.status_code == HTTPStatus.OK
    assert response.data == {"status": "ok"}
    assert orden.estado == OrdenPago.Estado.PAGADA
    assert orden.venta.estado == Venta.Estado.PAGADA
    assert EventoPago.objects.get().resultado == EventoPago.Resultado.PROCESADO


def test_a_duplicate_is_acknowledged_once(orden):
    enviar(orden, "confirmacion")

    response = enviar(orden, "confirmacion")

    assert response.status_code == HTTPStatus.OK
    assert EventoPago.objects.count() == 1


def test_a_forged_signature_is_refused_and_logged(orden):
    response = enviar(orden, "confirmacion", firma="forged")

    orden.refresh_from_db()
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert orden.estado == OrdenPago.Estado.PENDIENTE
    assert EventoPago.objects.get().resultado == EventoPago.Resultado.FIRMA_INVALIDA


def test_a_rejection_after_payment_is_ignored(orden):
    enviar(orden, "confirmacion")

    response = enviar(orden, "rechazo")

    orden.refresh_from_db()
    assert response.status_code == HTTPStatus.OK
    assert orden.estado == OrdenPago.Estado.PAGADA
    assert (
        EventoPago.objects.filter(resultado=EventoPago.Resultado.IGNORADO).count() == 1
    )


@pytest.mark.parametrize(
    ("monto", "esperado"),
    [(None, HTTPStatus.OK), ("1", HTTPStatus.BAD_REQUEST)],
)
def test_validation_checks_the_amount(orden, monto, esperado):
    extra = {"amount": monto} if monto else {}

    assert enviar(orden, "validacion", **extra).status_code == esperado


def test_an_unknown_order_is_refused():
    desconocida = OrdenPagoFactory.build(id_externo="KLAP-X", monto=1)

    assert enviar(desconocida, "confirmacion").status_code == HTTPStatus.BAD_REQUEST


def test_another_provider_is_not_found(orden, settings):
    settings.PAYMENT_PROVIDER = "simulated"

    assert enviar(orden, "confirmacion").status_code == HTTPStatus.NOT_FOUND
