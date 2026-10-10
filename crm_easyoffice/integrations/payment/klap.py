"""Klap Checkout Flex adapter.

ASSUMPTION: pending validation with Easy Office. The company has not chosen a
provider; Klap is one candidate, selected with ``PAYMENT_PROVIDER=klap``.

API reference: https://developers.klap.cl/documentacion-api
"""

from __future__ import annotations

import hashlib
import hmac
from decimal import Decimal
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import Any

import httpx

from .base import PaymentError
from .base import PaymentProvider
from .base import PaymentRequest
from .base import PaymentResult
from .base import PaymentStatus
from .montos import a_decimal
from .montos import a_entero

if TYPE_CHECKING:
    from collections.abc import Sequence

ORDERS_PATH = "/payment-gateway/v1/orders"

ESTADOS_ORDEN = {
    "pending": PaymentStatus.PENDING,
    "completed": PaymentStatus.PAID,
    "canceled": PaymentStatus.CANCELLED,
    "expired": PaymentStatus.EXPIRED,
    "refund": PaymentStatus.REFUNDED,
    "refunded": PaymentStatus.REFUNDED,
}

EVENTOS_WEBHOOK = {
    "validacion": PaymentStatus.PENDING,
    "confirmacion": PaymentStatus.PAID,
    "rechazo": PaymentStatus.REJECTED,
}

DETALLES_WEBHOOK = {
    "method": "payment_method",
    "brand": "brand",
    "card_type": "card_type",
    "last_digits": "last_digits",
    "installments": "quotas_number",
    "wallet": "wallet",
}

KLAP_WEBHOOK_KEYS = {
    "validacion": "webhook_validation",
    "confirmacion": "webhook_confirm",
    "rechazo": "webhook_reject",
}


def firma_webhook(reference_id: str, order_id: str, api_key: str) -> str:
    """The ``Apikey`` header Klap sends with every webhook."""
    clave = f"{reference_id}{order_id}{api_key}"
    return hashlib.sha256(clave.encode()).hexdigest()


class KlapPaymentProvider(PaymentProvider):
    def __init__(  # noqa: PLR0913
        self,
        api_key: str,
        base_url: str,
        *,
        methods: Sequence[str] = ("tarjetas",),
        expiration_minutes: int = 30,
        client: httpx.Client | None = None,
        timeout: float = 10,
    ) -> None:
        if not api_key:
            msg = "KLAP_API_KEY is not configured."
            raise PaymentError(msg)
        self.api_key = api_key
        self.methods = list(methods)
        self.expiration_minutes = expiration_minutes
        self.client = client or httpx.Client(
            base_url=base_url,
            timeout=timeout,
        )
        self.client.headers["apikey"] = api_key

    def create_payment(self, request: PaymentRequest) -> PaymentResult:
        if not request.notification_url:
            msg = "Klap requires webhook URLs; set PAYMENT_WEBHOOK_BASE_URL."
            raise PaymentError(msg)
        body: dict[str, Any] = {
            "reference_id": request.reference,
            "description": request.description or request.reference,
            "amount": {"currency": request.currency, "total": a_entero(request.amount)},
            "methods": self.methods,
            "items": [
                {
                    "code": item.code,
                    "name": item.name,
                    "unit_price": a_entero(item.unit_price),
                    "quantity": item.quantity,
                    "price": a_entero(item.unit_price * item.quantity),
                }
                for item in request.items
            ],
            "urls": {
                "return_url": request.return_url,
                "cancel_url": request.cancel_url or request.return_url,
            },
            "customs": [
                {
                    "key": "tarjetas_expiration_minutes",
                    "value": str(self.expiration_minutes),
                },
            ],
        }
        if request.payer is not None:
            body["user"] = {
                "email": request.payer.email,
                "rut": request.payer.rut.replace("-", ""),
                "first_name": request.payer.first_name,
                "last_name": request.payer.last_name,
            }
        body["webhooks"] = {
            clave_klap: f"{request.notification_url}{evento}/"
            for evento, clave_klap in KLAP_WEBHOOK_KEYS.items()
        }

        return self._resultado_orden(self._enviar("POST", ORDERS_PATH, json=body))

    def get_status(self, external_id: str) -> PaymentResult:
        return self._resultado_orden(
            self._enviar("GET", f"{ORDERS_PATH}/{external_id}"),
        )

    def confirm(self, external_id: str) -> PaymentResult:
        return self.get_status(external_id)

    def refund(self, external_id: str, amount: Decimal | None = None) -> PaymentResult:
        if amount is None:
            amount = self.get_status(external_id).amount
        datos = self._enviar(
            "POST",
            f"{ORDERS_PATH}/{external_id}/refund",
            json={"amount": a_entero(amount or Decimal(0))},
        )
        return PaymentResult(
            external_id=external_id,
            reference=str(datos.get("reference_id", "")),
            status=PaymentStatus.REFUNDED,
            amount=a_decimal(datos.get("amount")),
            raw_response=datos,
        )

    def parse_webhook(
        self,
        payload: dict,
        headers: dict[str, str],
        *,
        event: str | None = None,
    ) -> PaymentResult:
        if event not in EVENTOS_WEBHOOK:
            msg = f"Unknown Klap webhook: {event!r}"
            raise PaymentError(msg)
        reference_id = str(payload.get("reference_id", ""))
        order_id = str(payload.get("order_id", ""))
        if event == "validacion":
            # Klap signs this call with the order_id but does not send it (the
            # order is not created yet), so it cannot be verified. It changes
            # nothing: the caller only checks the reference and the amount.
            return PaymentResult(
                external_id="",
                reference=reference_id,
                status=PaymentStatus.PENDING,
                amount=a_decimal(payload.get("amount")),
                raw_response=dict(payload),
            )
        recibida = next(
            (valor for clave, valor in headers.items() if clave.lower() == "apikey"),
            "",
        )
        esperada = firma_webhook(reference_id, order_id, self.api_key)
        if not (reference_id and order_id and hmac.compare_digest(recibida, esperada)):
            msg = "The Klap webhook signature does not match."
            raise PaymentError(msg)

        return PaymentResult(
            external_id=order_id,
            reference=reference_id,
            status=EVENTOS_WEBHOOK[event],
            amount=a_decimal(payload.get("amount")),
            authorization_code=payload.get("mc_code") or None,
            details={
                clave: str(payload[clave_klap])
                for clave, clave_klap in DETALLES_WEBHOOK.items()
                if payload.get(clave_klap) not in (None, "")
            },
            raw_response=dict(payload),
        )

    def _enviar(self, method: str, path: str, **kwargs: Any) -> dict:
        try:
            response = self.client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            msg = f"Klap did not answer: {exc}"
            raise PaymentError(msg, transient=True) from exc
        if response.is_error:
            msg = f"Klap answered {response.status_code}: {response.text[:300]}"
            raise PaymentError(
                msg,
                transient=response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        try:
            return response.json()
        except ValueError as exc:
            msg = "Klap answered with a body that is not JSON."
            raise PaymentError(msg) from exc

    @staticmethod
    def _resultado_orden(datos: dict) -> PaymentResult:
        estado = str(datos.get("status", ""))
        if estado not in ESTADOS_ORDEN:
            msg = f"Unknown Klap order status: {estado!r}"
            raise PaymentError(msg)
        return PaymentResult(
            external_id=str(datos.get("order_id", "")),
            reference=str(datos.get("reference_id", "")),
            status=ESTADOS_ORDEN[estado],
            amount=a_decimal(datos.get("amount")),
            currency=(datos.get("amount") or {}).get("currency", "CLP"),
            redirect_url=datos.get("redirect_url"),
            raw_response=datos,
        )
