"""An advanced-signature provider reached over HTTP.

Today it talks to the test PSC (``firma-sandbox``), a fictitious provider
with no legal validity. The adapter knows that provider only through its
HTTP API, exactly as it would know a real one: an API key in
``Authorization: Bearer``, JSON resources, signed webhooks.

Every provider-specific name lives in the mapping section below
(``_formulario``, ``_resultado``, ``ESTADOS``, ``EVENTOS`` and the webhook
headers). When tufirma.digital's credentials and reference arrive, a copy of
this adapter with that mapping, its URL and its key is all that changes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from http import HTTPStatus
from typing import Any

import httpx

from .base import SignatureError
from .base import SignatureEvent
from .base import SignatureEventType
from .base import SignatureProvider
from .base import SignatureRequest
from .base import SignatureResult
from .base import SignatureStatus
from .base import SignerState
from .base import SignerStatus

# -- Mapping: the provider's vocabulary ----------------------------------------

ESTADOS = {
    "pendiente": SignatureStatus.PENDING,
    "completada": SignatureStatus.SIGNED,
    "rechazada": SignatureStatus.REJECTED,
    "cancelada": SignatureStatus.REJECTED,
    "expirada": SignatureStatus.EXPIRED,
}
ESTADOS_FIRMANTE = {
    "pendiente": SignerState.PENDING,
    "firmado": SignerState.SIGNED,
    "rechazado": SignerState.DECLINED,
}
EVENTOS = {
    "firmante.firmo": SignatureEventType.SIGNER_SIGNED,
    "firmante.rechazo": SignatureEventType.SIGNER_DECLINED,
    "solicitud.completada": SignatureEventType.COMPLETED,
    "solicitud.expirada": SignatureEventType.EXPIRED,
}
AMBIENTE_PRUEBAS = "pruebas"
ENCABEZADO_EVENTO = "x-psc-evento"
ENCABEZADO_TIMESTAMP = "x-psc-timestamp"
ENCABEZADO_FIRMA = "x-psc-firma"
VERSION_FIRMA = "v1="


def _formulario(request: SignatureRequest) -> dict[str, Any]:
    return {
        "nombre_documento": request.document_name,
        "referencia_externa": request.document_id,
        "url_notificacion": request.callback_url or "",
        "expira_en": request.expires_at,
        "firmantes": [
            {
                "orden": signer.order,
                "nombre": signer.full_name,
                "rut": signer.rut or "",
                "email": signer.email,
                "rol": signer.role,
                "referencia": signer.reference,
            }
            for signer in request.signers
        ],
    }


def _resultado(datos: dict[str, Any]) -> SignatureResult:
    try:
        firmantes = [
            SignerStatus(
                reference=str(f.get("referencia", "")),
                external_id=str(f["id"]),
                order=int(f["orden"]),
                status=ESTADOS_FIRMANTE[f["estado"]],
                signed_at=f.get("firmado_en"),
                declined_at=f.get("rechazado_en"),
                declined_reason=f.get("motivo_rechazo") or "",
            )
            for f in datos.get("firmantes", [])
        ]
        estado = ESTADOS[datos["estado"]]
        external_id = str(datos["id"])
    except (KeyError, TypeError, ValueError) as exc:
        msg = f"Unexpected answer from the signature provider: {exc!r}"
        raise SignatureError(msg) from exc
    if estado is SignatureStatus.PENDING and any(
        f.status is SignerState.SIGNED for f in firmantes
    ):
        estado = SignatureStatus.PARTIALLY_SIGNED
    return SignatureResult(
        external_id=external_id,
        status=estado,
        signed_hash=datos.get("sha256_firmado"),
        signed_at=datos.get("terminada_en")
        if estado is SignatureStatus.SIGNED
        else None,
        raw_response=datos,
        signers=firmantes,
        original_sha256=datos.get("sha256_original"),
        test_environment=datos.get("ambiente") == AMBIENTE_PRUEBAS,
    )


def firma_webhook(secreto: str, timestamp: str, body: bytes) -> str:
    mensaje = f"{timestamp}.".encode() + body
    digest = hmac.new(secreto.encode(), mensaje, hashlib.sha256).hexdigest()
    return VERSION_FIRMA + digest


# -- The adapter ---------------------------------------------------------------


class HttpSignatureProvider(SignatureProvider):
    def __init__(  # noqa: PLR0913
        self,
        base_url: str,
        api_key: str,
        webhook_secret: str,
        *,
        tolerance_seconds: int = 300,
        client: httpx.Client | None = None,
        timeout: float = 30,
    ) -> None:
        if not (base_url and api_key and webhook_secret):
            msg = "The signature provider needs a base URL, an API key and a secret."
            raise SignatureError(msg)
        self.webhook_secret = webhook_secret
        self.tolerance_seconds = tolerance_seconds
        self.client = client or httpx.Client(base_url=base_url, timeout=timeout)
        self.client.headers["Authorization"] = f"Bearer {api_key}"

    def create_request(self, request: SignatureRequest) -> SignatureResult:
        if not request.signers:
            msg = "A signature request needs at least one signer."
            raise SignatureError(msg)
        respuesta = self._enviar(
            "POST",
            "solicitudes",
            files={
                "documento": (
                    f"{request.document_id}.pdf",
                    request.content,
                    "application/pdf",
                ),
            },
            data={"datos": json.dumps(_formulario(request), ensure_ascii=False)},
        )
        return _resultado(respuesta.json())

    def get_status(self, external_id: str) -> SignatureResult:
        return _resultado(self._enviar("GET", f"solicitudes/{external_id}").json())

    def download_signed(self, external_id: str) -> bytes:
        return self._enviar("GET", f"solicitudes/{external_id}/documento").content

    def cancel(self, external_id: str) -> SignatureResult:
        return _resultado(
            self._enviar("POST", f"solicitudes/{external_id}/cancelar").json(),
        )

    def resend(self, external_id: str, signer_external_id: str) -> None:
        self._enviar(
            "POST",
            f"solicitudes/{external_id}/firmantes/{signer_external_id}/reenviar",
        )

    def parse_webhook(self, body: bytes, headers: dict[str, str]) -> SignatureEvent:
        """Verify the HMAC and the timestamp window, then read the event."""
        encabezados = {clave.lower(): valor for clave, valor in headers.items()}
        timestamp = encabezados.get(ENCABEZADO_TIMESTAMP, "")
        recibida = encabezados.get(ENCABEZADO_FIRMA, "")
        esperada = firma_webhook(self.webhook_secret, timestamp, body)
        if not (timestamp and hmac.compare_digest(recibida, esperada)):
            msg = "The signature webhook's HMAC does not match."
            raise SignatureError(msg)
        try:
            desfase = abs(time.time() - int(timestamp))
        except ValueError as exc:
            msg = "The signature webhook's timestamp is not a number."
            raise SignatureError(msg) from exc
        if desfase > self.tolerance_seconds:
            msg = "The signature webhook is outside the timestamp window."
            raise SignatureError(msg)
        try:
            payload = json.loads(body)
            tipo = EVENTOS[payload["tipo"]]
            event_id = str(payload["id_evento"])
        except (ValueError, KeyError, TypeError) as exc:
            msg = "The signature webhook's body is not a known event."
            raise SignatureError(msg) from exc
        if event_id != encabezados.get(ENCABEZADO_EVENTO, event_id):
            msg = "The signature webhook's event id does not match its header."
            raise SignatureError(msg)
        return SignatureEvent(
            event_id=event_id,
            type=tipo,
            result=_resultado(payload.get("solicitud") or {}),
        )

    def _enviar(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self.client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            msg = f"The signature provider did not answer: {exc}"
            raise SignatureError(msg, transient=True) from exc
        if response.is_error:
            msg = (
                f"The signature provider answered {response.status_code}: "
                f"{response.text[:300]}"
            )
            raise SignatureError(
                msg,
                transient=response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        return response
