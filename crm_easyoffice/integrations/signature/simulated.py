"""A simulated signature provider.

This exists because the real provider's credentials are not available. It
satisfies the same contract as a real implementation, so the rest of the system
can be built, tested and demonstrated without them, and swapping in the real
provider is a settings change rather than a refactor.

It keeps its state in memory: it is a development and test double, not a
fixture for anything that must survive a process restart.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC
from datetime import datetime

from .base import SignatureError
from .base import SignatureProvider
from .base import SignatureRequest
from .base import SignatureResult
from .base import SignatureStatus


class SimulatedSignatureProvider(SignatureProvider):
    """In-memory signature provider that completes immediately.

    ``auto_sign=False`` leaves requests PENDING so a caller can drive the
    transitions explicitly, which is what the state-machine tests need.
    """

    def __init__(self, *, auto_sign: bool = True) -> None:
        self.auto_sign = auto_sign
        self._requests: dict[str, SignatureResult] = {}
        self._originals: dict[str, bytes] = {}

    def create_request(self, request: SignatureRequest) -> SignatureResult:
        if not request.signers:
            msg = "A signature request needs at least one signer."
            raise SignatureError(msg)

        external_id = f"sim-{uuid.uuid4()}"
        self._originals[external_id] = request.content

        if self.auto_sign:
            result = self._sign(external_id, request.content)
        else:
            result = SignatureResult(
                external_id=external_id,
                status=SignatureStatus.PENDING,
                raw_response={"simulated": True, "signers": len(request.signers)},
            )

        self._requests[external_id] = result
        return result

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
        cancelled = SignatureResult(
            external_id=external_id,
            status=SignatureStatus.REJECTED,
            raw_response={"simulated": True, "cancelled": True},
        )
        self._requests[external_id] = cancelled
        return cancelled

    def parse_webhook(self, payload: dict, headers: dict[str, str]) -> SignatureResult:
        """Interpret a webhook shaped the way this simulator emits them.

        A real adapter verifies a signature header here. There is nothing to
        verify against, so this only checks the payload is well formed.
        """
        external_id = payload.get("external_id")
        raw_status = payload.get("status")
        if not external_id or not raw_status:
            msg = "Webhook payload must carry 'external_id' and 'status'."
            raise SignatureError(msg)

        try:
            status = SignatureStatus(raw_status)
        except ValueError as exc:
            msg = f"Unknown signature status: {raw_status!r}"
            raise SignatureError(msg) from exc

        if status is SignatureStatus.SIGNED and external_id in self._originals:
            result = self._sign(external_id, self._originals[external_id])
        else:
            result = SignatureResult(
                external_id=external_id,
                status=status,
                raw_response=dict(payload),
            )

        self._requests[external_id] = result
        return result

    # -- internals ----------------------------------------------------------

    def _get(self, external_id: str) -> SignatureResult:
        try:
            return self._requests[external_id]
        except KeyError as exc:
            msg = f"Unknown signature process: {external_id}"
            raise SignatureError(msg) from exc

    def _sign(self, external_id: str, content: bytes) -> SignatureResult:
        """Produce a deterministic stand-in for a signed file.

        The marker makes it obvious in any environment that this file was not
        signed by a real provider and has no legal value.
        """
        signed = content + f"\n<!-- SIMULATED SIGNATURE {external_id} -->".encode()
        return SignatureResult(
            external_id=external_id,
            status=SignatureStatus.SIGNED,
            signed_content=signed,
            signed_hash=hashlib.sha256(signed).hexdigest(),
            signed_at=datetime.now(UTC).isoformat(),
            raw_response={"simulated": True},
        )
