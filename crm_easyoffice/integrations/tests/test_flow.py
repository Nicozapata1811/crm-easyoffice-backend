"""Flow adapter tests. No request leaves the process; the data is synthetic."""

from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal
from urllib.parse import parse_qs

import httpx
import pytest

from crm_easyoffice.integrations.payment.base import Payer
from crm_easyoffice.integrations.payment.base import PaymentError
from crm_easyoffice.integrations.payment.base import PaymentRequest
from crm_easyoffice.integrations.payment.base import PaymentStatus
from crm_easyoffice.integrations.payment.flow import FlowPaymentProvider
from crm_easyoffice.integrations.payment.flow import firmar

API_KEY = "synthetic-api-key"
SECRET = "synthetic-secret"  # noqa: S105
BASE_URL = "https://flow.invalid/api"


def provider_answering(handler) -> tuple[FlowPaymentProvider, list[httpx.Request]]:
    enviados: list[httpx.Request] = []

    def registrar(request: httpx.Request) -> httpx.Response:
        enviados.append(request)
        return handler(request)

    client = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(registrar))
    return FlowPaymentProvider(API_KEY, SECRET, BASE_URL, client=client), enviados


def estado_flow(status: int = 2, **extra) -> dict:
    return {
        "flowOrder": 3567899,
        "commerceOrder": "ref-1",
        "status": status,
        "amount": 18400,
        "currency": "CLP",
        "paymentData": {"media": "Webpay", "date": "2026-10-10 12:32:11"},
        **extra,
    }


def solicitud(**overrides) -> PaymentRequest:
    datos = {
        "reference": "ref-1",
        "amount": Decimal(18400),
        "description": "Easy Office VEN-000001",
        "return_url": "https://api.invalid/api/pagos/retorno/1/",
        "notification_url": "https://api.invalid/api/pagos/webhooks/flow/",
        "payer": Payer(email="cliente@example.test", rut="41000010-5"),
    }
    return PaymentRequest(**{**datos, **overrides})


def test_signature_follows_the_documented_example():
    params = {"apiKey": "XXXX-XXXX-XXXX", "currency": "CLP", "amount": 5000}

    esperada = hmac.new(
        SECRET.encode(),
        b"amount5000apiKeyXXXX-XXXX-XXXXcurrencyCLP",
        hashlib.sha256,
    ).hexdigest()
    assert firmar(params, SECRET) == esperada


class TestCreatePayment:
    def test_posts_a_signed_form_and_builds_the_checkout_url(self):
        provider, enviados = provider_answering(
            lambda _: httpx.Response(
                200,
                json={
                    "url": "https://flow.invalid/pay",
                    "token": "TOK",
                    "flowOrder": 77,
                },
            ),
        )

        resultado = provider.create_payment(solicitud())

        request = enviados[0]
        form = {
            clave: valores[0]
            for clave, valores in parse_qs(request.content.decode()).items()
        }
        firma = form.pop("s")
        assert request.method == "POST"
        assert request.url.path == "/api/payment/create"
        assert firma == firmar(form, SECRET)
        assert form["apiKey"] == API_KEY
        assert form["commerceOrder"] == "ref-1"
        assert form["amount"] == "18400"
        assert form["paymentMethod"] == "9"
        assert form["urlConfirmation"].endswith("/webhooks/flow/confirmacion/")
        assert json.loads(form["optional"]) == {"rut": "41000010-5"}
        assert resultado.external_id == "77"
        assert resultado.redirect_url == "https://flow.invalid/pay?token=TOK"
        assert resultado.status is PaymentStatus.PENDING

    @pytest.mark.parametrize(
        "overrides",
        [{"notification_url": None}, {"return_url": None}, {"payer": Payer(email="")}],
    )
    def test_refuses_without_urls_or_email(self, overrides):
        provider, enviados = provider_answering(lambda _: httpx.Response(200, json={}))

        with pytest.raises(PaymentError):
            provider.create_payment(solicitud(**overrides))

        assert enviados == []

    @pytest.mark.parametrize(
        ("status", "transient"),
        [(500, True), (400, False), (401, False)],
    )
    def test_http_errors_say_whether_to_retry(self, status, transient):
        provider, _ = provider_answering(lambda _: httpx.Response(status, json={}))

        with pytest.raises(PaymentError) as error:
            provider.create_payment(solicitud())

        assert error.value.transient is transient


@pytest.mark.parametrize(
    ("flow", "nuestro"),
    [
        (1, PaymentStatus.PENDING),
        (2, PaymentStatus.PAID),
        (3, PaymentStatus.REJECTED),
        (4, PaymentStatus.CANCELLED),
    ],
)
def test_get_status_maps_flow_states(flow, nuestro):
    provider, enviados = provider_answering(
        lambda _: httpx.Response(200, json=estado_flow(flow)),
    )

    resultado = provider.get_status("3567899")

    params = dict(enviados[0].url.params)
    firma = params.pop("s")
    assert enviados[0].url.path == "/api/payment/getStatusByFlowOrder"
    assert params["flowOrder"] == "3567899"
    assert firma == firmar(params, SECRET)
    assert resultado.status is nuestro


class TestWebhook:
    def test_verifies_the_token_by_asking_flow(self):
        provider, enviados = provider_answering(
            lambda _: httpx.Response(200, json=estado_flow()),
        )

        resultado = provider.parse_webhook({"token": "TOK"}, {}, event="confirmacion")

        assert enviados[0].url.path == "/api/payment/getStatus"
        assert enviados[0].url.params["token"] == "TOK"  # noqa: S105
        assert resultado.status is PaymentStatus.PAID
        assert resultado.reference == "ref-1"
        assert resultado.external_id == "3567899"
        assert resultado.amount == Decimal(18400)
        assert resultado.details == {"method": "Webpay"}

    def test_an_unknown_token_is_rejected(self):
        provider, _ = provider_answering(
            lambda _: httpx.Response(
                400,
                json={"code": 105, "message": "Token invalid"},
            ),
        )

        with pytest.raises(PaymentError) as error:
            provider.parse_webhook({"token": "NOPE"}, {}, event="confirmacion")

        assert not error.value.transient

    def test_a_notification_without_token_is_rejected(self):
        provider, enviados = provider_answering(lambda _: httpx.Response(200, json={}))

        with pytest.raises(PaymentError):
            provider.parse_webhook({}, {}, event="confirmacion")

        assert enviados == []


def test_requires_both_keys():
    with pytest.raises(PaymentError):
        FlowPaymentProvider(API_KEY, "", BASE_URL)
