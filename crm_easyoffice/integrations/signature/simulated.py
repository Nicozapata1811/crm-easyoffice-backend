"""A simulated signature provider.

This exists because the real provider's credentials are not available. It
satisfies the same contract as a real implementation, so the rest of the system
can be built, tested and demonstrated without them, and swapping in the real
provider is a settings change rather than a refactor.

It keeps its state in memory: it is a development and test double, not a
fixture for anything that must survive a process restart.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import uuid
from datetime import UTC
from datetime import datetime

from .base import SignatureError
from .base import SignatureEvent
from .base import SignatureEventType
from .base import SignatureProvider
from .base import SignatureRequest
from .base import SignatureResult
from .base import SignatureStatus
from .base import SignerState
from .base import SignerStatus


def _ahora() -> str:
    return datetime.now(UTC).isoformat()


class SimulatedSignatureProvider(SignatureProvider):
    """In-memory signature provider that completes immediately.

    ``auto_sign=False`` leaves requests PENDING so a caller can drive the
    transitions explicitly (``sign_next``, ``decline``, ``expire``), which is
    what the state-machine tests need.
    """

    def __init__(self, *, auto_sign: bool = True) -> None:
        self.auto_sign = auto_sign
        self._requests: dict[str, SignatureResult] = {}
        self._originals: dict[str, bytes] = {}
        self.resent: list[tuple[str, str]] = []

    def create_request(self, request: SignatureRequest) -> SignatureResult:
        if not request.signers:
            msg = "A signature request needs at least one signer."
            raise SignatureError(msg)

        external_id = f"sim-{uuid.uuid4()}"
        self._originals[external_id] = request.content
        firmantes = [
            SignerStatus(
                reference=signer.reference,
                external_id=f"{external_id}-{signer.order}",
                order=signer.order,
                status=SignerState.PENDING,
            )
            for signer in sorted(request.signers, key=lambda s: s.order)
        ]
        self._requests[external_id] = SignatureResult(
            external_id=external_id,
            status=SignatureStatus.PENDING,
            raw_response={"simulated": True, "signers": len(request.signers)},
            signers=firmantes,
            original_sha256=hashlib.sha256(request.content).hexdigest(),
        )
        if self.auto_sign:
            while self._get(external_id).status is not SignatureStatus.SIGNED:
                self.sign_next(external_id)
        return self._get(external_id)

    def get_status(self, external_id: str) -> SignatureResult:
        return self._get(external_id)

    def download_signed(self, external_id: str) -> bytes:
        result = self._get(external_id)
        if result.status is not SignatureStatus.SIGNED:
            msg = f"Signature process {external_id} is {result.status}, not signed."
            raise SignatureError(msg)
        return result.signed_content or b""

    def cancel(self, external_id: str) -> SignatureResult:
        result = self._get(external_id)
        if result.status is SignatureStatus.SIGNED:
            msg = f"Signature process {external_id} has already completed."
            raise SignatureError(msg)
        return self._update(
            external_id,
            status=SignatureStatus.REJECTED,
            raw_response={"simulated": True, "cancelled": True},
        )

    def resend(self, external_id: str, signer_external_id: str) -> None:
        self._get(external_id)
        self.resent.append((external_id, signer_external_id))

    def parse_webhook(self, body: bytes, headers: dict[str, str]) -> SignatureEvent:
        """Interpret a webhook shaped the way ``event`` builds them.

        A real adapter verifies a signature header here. There is nothing to
        verify against, so this only checks the payload is well formed.
        """
        try:
            payload = json.loads(body)
            external_id = payload["external_id"]
            tipo = SignatureEventType(payload["type"])
        except (ValueError, KeyError, TypeError) as exc:
            msg = "Webhook payload must carry 'external_id' and a known 'type'."
            raise SignatureError(msg) from exc
        return SignatureEvent(
            event_id=payload.get("event_id") or str(uuid.uuid4()),
            type=tipo,
            result=self._get(external_id),
        )

    # -- driving the simulation (tests and demos) ---------------------------

    def event(self, external_id: str, tipo: SignatureEventType) -> bytes:
        """The webhook body this provider would send now."""
        payload = {
            "event_id": str(uuid.uuid4()),
            "type": str(tipo),
            "external_id": external_id,
        }
        return json.dumps(payload).encode()

    def sign_next(self, external_id: str) -> SignatureResult:
        result = self._get(external_id)
        firmantes = list(result.signers)
        siguiente = next(
            i for i, s in enumerate(firmantes) if s.status is SignerState.PENDING
        )
        firmantes[siguiente] = dataclasses.replace(
            firmantes[siguiente],
            status=SignerState.SIGNED,
            signed_at=_ahora(),
        )
        if any(s.status is SignerState.PENDING for s in firmantes):
            return self._update(
                external_id,
                status=SignatureStatus.PARTIALLY_SIGNED,
                signers=firmantes,
            )
        signed = self._originals[external_id] + (
            f"\n%% SIMULATED SIGNATURE {external_id}\n".encode()
        )
        return self._update(
            external_id,
            status=SignatureStatus.SIGNED,
            signers=firmantes,
            signed_content=signed,
            signed_hash=hashlib.sha256(signed).hexdigest(),
            signed_at=_ahora(),
        )

    def decline(self, external_id: str, reason: str) -> SignatureResult:
        result = self._get(external_id)
        firmantes = list(result.signers)
        siguiente = next(
            i for i, s in enumerate(firmantes) if s.status is SignerState.PENDING
        )
        firmantes[siguiente] = dataclasses.replace(
            firmantes[siguiente],
            status=SignerState.DECLINED,
            declined_at=_ahora(),
            declined_reason=reason,
        )
        return self._update(
            external_id,
            status=SignatureStatus.REJECTED,
            signers=firmantes,
        )

    def expire(self, external_id: str) -> SignatureResult:
        return self._update(external_id, status=SignatureStatus.EXPIRED)

    # -- internals ----------------------------------------------------------

    def _get(self, external_id: str) -> SignatureResult:
        try:
            return self._requests[external_id]
        except KeyError as exc:
            msg = f"Unknown signature process: {external_id}"
            raise SignatureError(msg) from exc

    def _update(self, external_id: str, **cambios) -> SignatureResult:
        result = dataclasses.replace(self._get(external_id), **cambios)
        self._requests[external_id] = result
        return result
