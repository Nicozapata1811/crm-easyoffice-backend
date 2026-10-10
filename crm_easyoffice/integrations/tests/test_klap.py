"""Klap adapter tests. No request leaves the process; the data is synthetic."""

from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest

from crm_easyoffice.integrations.payment.base import Payer
from crm_easyoffice.integrations.payment.base import PaymentError
from crm_easyoffice.integrations.payment.base import PaymentItem
from crm_easyoffice.integrations.payment.base import PaymentRequest
from crm_easyoffice.integrations.payment.base import PaymentStatus
from crm_easyoffice.integrations.payment.klap import KlapPaymentProvider
from crm_easyoffice.integrations.payment.klap import firma_webhook

API_KEY = "synthetic-api-key"
BASE_URL = "https://klap.invalid"


def provider_answering(handler) -> tuple[KlapPaymentProvider, list[httpx.Request]]:
    enviados: list[httpx.Request] = []

    def registrar(request: httpx.Request) -> httpx.Response:
        enviados.append(request)
        return handler(request)

    client = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(registrar))
    return KlapPaymentProvider(API_KEY, BASE_URL, client=client), enviados


def orden_klap(status: str = "pending", **extra) -> dict:
    return {
        "order_id": "KLAP-1",
        "reference_id": "ref-1",
        "status": status,
        "amount": {"currency": "CLP", "total": 18400},
        "redirect_url": "https://klap.invalid/order/KLAP-1",
        **extra,
    }


def solicitud(**overrides) -> PaymentRequest:
    datos = {
        "reference": "ref-1",
        "amount": Decimal(18400),
        "description": "Easy Office VEN-000001",
        "return_url": "https://portal.invalid/pagos/1/resultado",
        "notification_url": "https://api.invalid/api/pagos/webhooks/klap/",
        "payer": Payer(
            email="cliente@example.test",
            rut="41000010-5",
            first_name="Ana",
        ),
        "items": (PaymentItem("domicilio", "Domicilio", Decimal(14900), 1),),
    }
    return PaymentRequest(**{**datos, **overrides})


class TestCreatePayment:
    def test_sends_the_order_with_the_api_key(self):
        provider, enviados = provider_answering(
            lambda _: httpx.Response(201, json=orden_klap()),
        )

        resultado = provider.create_payment(solicitud())

        request = enviados[0]
        body = json.loads(request.content)
        assert request.method == "POST"
        assert request.url.path == "/payment-gateway/v1/orders"
        assert request.headers["apikey"] == API_KEY
        assert body["amount"] == {"currency": "CLP", "total": 18400}
        assert body["user"]["rut"] == "410000105"
        assert body["items"][0]["price"] == 14900  # noqa: PLR2004
        assert body["webhooks"]["webhook_confirm"].endswith("/klap/confirmacion/")
        assert body["urls"]["cancel_url"] == body["urls"]["return_url"]
        assert resultado.external_id == "KLAP-1"
        assert resultado.status is PaymentStatus.PENDING
        assert resultado.redirect_url

    def test_refuses_an_order_without_webhook_urls(self):
        provider, enviados = provider_answering(
            lambda _: httpx.Response(201, json=orden_klap()),
        )

        with pytest.raises(PaymentError):
            provider.create_payment(solicitud(notification_url=None))

        assert enviados == []

    @pytest.mark.parametrize(
        ("status", "transient"),
        [(500, True), (503, True), (400, False), (401, False)],
    )
    def test_http_errors_say_whether_to_retry(self, status, transient):
        provider, _ = provider_answering(lambda _: httpx.Response(status, json={}))

        with pytest.raises(PaymentError) as error:
            provider.create_payment(solicitud())

        assert error.value.transient is transient

    def test_network_failures_are_transient(self):
        def caer(request):
            msg = "timeout"
            raise httpx.ConnectTimeout(msg, request=request)

        provider, _ = provider_answering(caer)

        with pytest.raises(PaymentError) as error:
            provider.create_payment(solicitud())

        assert error.value.transient


@pytest.mark.parametrize(
    ("klap", "nuestro"),
    [
        ("pending", PaymentStatus.PENDING),
        ("completed", PaymentStatus.PAID),
        ("canceled", PaymentStatus.CANCELLED),
        ("expired", PaymentStatus.EXPIRED),
    ],
)
def test_get_status_maps_order_states(klap, nuestro):
    provider, enviados = provider_answering(
        lambda _: httpx.Response(200, json=orden_klap(klap)),
    )

    resultado = provider.get_status("KLAP-1")

    assert enviados[0].url.path == "/payment-gateway/v1/orders/KLAP-1"
    assert resultado.status is nuestro
    assert resultado.amount == Decimal(18400)


def test_refund_posts_the_amount():
    provider, enviados = provider_answering(
        lambda _: httpx.Response(201, json={"reference_id": "ref-1", "amount": 500}),
    )

    resultado = provider.refund("KLAP-1", Decimal(500))

    assert enviados[0].url.path == "/payment-gateway/v1/orders/KLAP-1/refund"
    assert json.loads(enviados[0].content) == {"amount": 500}
    assert resultado.status is PaymentStatus.REFUNDED


class TestWebhook:
    payload = {
        "order_id": "KLAP-1",
        "reference_id": "ref-1",
        "amount": "18400",
        "mc_code": "MC-1",
        "brand": "VISA",
        "last_digits": "1000",
        "quotas_number": "3",
    }

    def provider(self) -> KlapPaymentProvider:
        return provider_answering(lambda _: httpx.Response(500))[0]

    def test_valid_signature_is_accepted(self):
        firma = firma_webhook("ref-1", "KLAP-1", API_KEY)

        resultado = self.provider().parse_webhook(
            self.payload,
            {"Apikey": firma},
            event="confirmacion",
        )

        assert resultado.status is PaymentStatus.PAID
        assert resultado.reference == "ref-1"
        assert resultado.authorization_code == "MC-1"
        assert resultado.details == {
            "brand": "VISA",
            "last_digits": "1000",
            "installments": "3",
        }

    @pytest.mark.parametrize("cabeceras", [{}, {"Apikey": "forged"}])
    def test_invalid_signature_is_rejected(self, cabeceras):
        with pytest.raises(PaymentError):
            self.provider().parse_webhook(self.payload, cabeceras, event="confirmacion")

    def test_amount_may_come_as_an_object(self):
        payload = {**self.payload, "amount": {"currency": "CLP", "total": 18400}}
        firma = firma_webhook("ref-1", "KLAP-1", API_KEY)

        resultado = self.provider().parse_webhook(
            payload,
            {"Apikey": firma},
            event="validacion",
        )

        assert resultado.amount == Decimal(18400)

    def test_unknown_event_is_rejected(self):
        firma = firma_webhook("ref-1", "KLAP-1", API_KEY)

        with pytest.raises(PaymentError):
            self.provider().parse_webhook(self.payload, {"apikey": firma}, event="otro")


def test_requires_an_api_key():
    with pytest.raises(PaymentError):
        KlapPaymentProvider("", BASE_URL)
