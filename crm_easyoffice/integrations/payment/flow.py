"""Flow adapter.

ASSUMPTION: pending validation with Easy Office. The company has not chosen a
provider; Flow is one candidate, enabled through ``PAYMENT_PROVIDERS``.

API reference: https://developers.flow.cl/api
"""

from __future__ import annotations

import hashlib
import hmac
import json
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
    from decimal import Decimal

ESTADOS_FLOW = {
    1: PaymentStatus.PENDING,
    2: PaymentStatus.PAID,
    3: PaymentStatus.REJECTED,
    4: PaymentStatus.CANCELLED,
}


def firmar(params: dict[str, Any], secret_key: str) -> str:
    """Flow's ``s``: HMAC-SHA256 of every ``name + value``, sorted by name."""
    texto = "".join(f"{clave}{params[clave]}" for clave in sorted(params))
    return hmac.new(secret_key.encode(), texto.encode(), hashlib.sha256).hexdigest()


class FlowPaymentProvider(PaymentProvider):
    """Flow's hosted checkout, reached by redirecting the browser.

    Flow's notification carries only a token, so ``parse_webhook`` verifies
    it by asking Flow for the payment behind it.
    """

    webhook_needs_lookup = True

    def __init__(  # noqa: PLR0913
        self,
        api_key: str,
        secret_key: str,
        base_url: str,
        *,
        payment_method: int = 9,
        expiration_minutes: int = 30,
        client: httpx.Client | None = None,
        timeout: float = 10,
    ) -> None:
        if not api_key or not secret_key:
            msg = "FLOW_API_KEY and FLOW_SECRET_KEY are not configured."
            raise PaymentError(msg)
        self.api_key = api_key
        self.secret_key = secret_key
        self.payment_method = payment_method
        self.expiration_minutes = expiration_minutes
        self.client = client or httpx.Client(base_url=base_url, timeout=timeout)

    def create_payment(self, request: PaymentRequest) -> PaymentResult:
        if not request.notification_url or not request.return_url:
            msg = "Flow requires confirmation and return URLs."
            raise PaymentError(msg)
        if request.payer is None or not request.payer.email:
            msg = "Flow requires the payer's email."
            raise PaymentError(msg)
        params: dict[str, Any] = {
            "commerceOrder": request.reference,
            "subject": request.description or request.reference,
            "currency": request.currency,
            "amount": a_entero(request.amount),
            "email": request.payer.email,
            "paymentMethod": self.payment_method,
            "urlConfirmation": f"{request.notification_url}confirmacion/",
            "urlReturn": request.return_url,
            "timeout": self.expiration_minutes * 60,
        }
        if request.payer.rut:
            params["optional"] = json.dumps({"rut": request.payer.rut})

        datos = self._enviar("POST", "/payment/create", params)
        if not datos.get("url") or not datos.get("token"):
            msg = f"Flow did not return a checkout URL: {datos!r}"
            raise PaymentError(msg)
        return PaymentResult(
            external_id=str(datos.get("flowOrder", "")),
            reference=request.reference,
            status=PaymentStatus.PENDING,
            amount=request.amount,
            currency=request.currency,
            redirect_url=f"{datos['url']}?token={datos['token']}",
            raw_response=datos,
        )

    def get_status(self, external_id: str) -> PaymentResult:
        return self._resultado(
            self._enviar(
                "GET",
                "/payment/getStatusByFlowOrder",
                {"flowOrder": external_id},
            ),
        )

    def confirm(self, external_id: str) -> PaymentResult:
        return self.get_status(external_id)

    def refund(self, external_id: str, amount: Decimal | None = None) -> PaymentResult:
        msg = "Refunds through Flow are not supported yet."
        raise PaymentError(msg)

    def parse_webhook(
        self,
        payload: dict,
        headers: dict[str, str],
        *,
        event: str | None = None,
    ) -> PaymentResult:
        token = str(payload.get("token", ""))
        if not token:
            msg = "The Flow notification has no token."
            raise PaymentError(msg)
        return self._resultado(
            self._enviar("GET", "/payment/getStatus", {"token": token}),
        )

    def _enviar(self, method: str, path: str, params: dict[str, Any]) -> dict:
        firmados = {"apiKey": self.api_key, **params}
        firmados["s"] = firmar(firmados, self.secret_key)
        datos = {"params": firmados} if method == "GET" else {"data": firmados}
        try:
            response = self.client.request(method, path, **datos)
        except httpx.HTTPError as exc:
            msg = f"Flow did not answer: {exc}"
            raise PaymentError(msg, transient=True) from exc
        if response.is_error:
            msg = f"Flow answered {response.status_code}: {response.text[:300]}"
            raise PaymentError(
                msg,
                transient=response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        try:
            return response.json()
        except ValueError as exc:
            msg = "Flow answered with a body that is not JSON."
            raise PaymentError(msg) from exc

    @staticmethod
    def _resultado(datos: dict) -> PaymentResult:
        try:
            estado = ESTADOS_FLOW[int(datos.get("status"))]
        except (TypeError, ValueError, KeyError) as exc:
            msg = f"Unknown Flow payment status: {datos.get('status')!r}"
            raise PaymentError(msg) from exc
        pago = datos.get("paymentData") or {}
        return PaymentResult(
            external_id=str(datos.get("flowOrder", "")),
            reference=str(datos.get("commerceOrder", "")),
            status=estado,
            amount=a_decimal(datos.get("amount")),
            currency=datos.get("currency") or "CLP",
            paid_at=pago.get("date"),
            details={"method": str(pago["media"])} if pago.get("media") else {},
            raw_response=datos,
        )
