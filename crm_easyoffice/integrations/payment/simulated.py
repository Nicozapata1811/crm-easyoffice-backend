"""A simulated payment provider.

This exists because the company has not chosen a provider. It satisfies the
same contract as a real implementation, so a case that requires payment can be
built and demonstrated end to end before that decision is made.

It keeps its state in memory: a development and test double, nothing more. It
moves no money and touches no card data.
"""

from __future__ import annotations

import uuid
from datetime import UTC
from datetime import datetime
from typing import TYPE_CHECKING

from .base import PaymentError
from .base import PaymentProvider
from .base import PaymentRequest
from .base import PaymentResult
from .base import PaymentStatus

if TYPE_CHECKING:
    from decimal import Decimal

SIMULATED_RETURN_URL = "https://simulated-payments.invalid/checkout"


class SimulatedPaymentProvider(PaymentProvider):
    """In-memory payment provider.

    ``auto_confirm=True`` settles a payment as soon as it is created, which is
    convenient for demonstrations. The default leaves it PENDING so the
    create, return and confirm round trip can be exercised as it would be with
    a real provider.
    """

    def __init__(self, *, auto_confirm: bool = False, approve: bool = True) -> None:
        self.auto_confirm = auto_confirm
        self.approve = approve
        self._payments: dict[str, PaymentResult] = {}

    def create_payment(self, request: PaymentRequest) -> PaymentResult:
        if request.amount <= 0:
            msg = "A payment amount must be greater than zero."
            raise PaymentError(msg)

        external_id = f"sim-{uuid.uuid4()}"
        result = PaymentResult(
            external_id=external_id,
            reference=request.reference,
            status=PaymentStatus.PENDING,
            amount=request.amount,
            currency=request.currency,
            redirect_url=f"{SIMULATED_RETURN_URL}?token={external_id}",
            raw_response={"simulated": True},
        )
        self._payments[external_id] = result

        if self.auto_confirm:
            result = self.confirm(external_id)
        return result

    def get_status(self, external_id: str) -> PaymentResult:
        return self._get(external_id)

    def confirm(self, external_id: str) -> PaymentResult:
        """Settle a pending payment.

        Calling this on an already-settled payment returns it unchanged rather
        than raising, because a real provider's return URL can be reloaded and
        its webhook can be delivered twice.
        """
        current = self._get(external_id)
        if current.status is not PaymentStatus.PENDING:
            return current

        if self.approve:
            settled = PaymentResult(
                external_id=external_id,
                reference=current.reference,
                status=PaymentStatus.PAID,
                amount=current.amount,
                currency=current.currency,
                authorization_code=uuid.uuid4().hex[:6].upper(),
                paid_at=datetime.now(UTC).isoformat(),
                raw_response={"simulated": True},
            )
        else:
            settled = PaymentResult(
                external_id=external_id,
                reference=current.reference,
                status=PaymentStatus.REJECTED,
                amount=current.amount,
                currency=current.currency,
                raw_response={"simulated": True, "reason": "simulated rejection"},
            )

        self._payments[external_id] = settled
        return settled

    def refund(self, external_id: str, amount: Decimal | None = None) -> PaymentResult:
        current = self._get(external_id)
        if current.status is not PaymentStatus.PAID:
            msg = (
                f"Payment {external_id} is {current.status}, so it cannot be refunded."
            )
            raise PaymentError(msg)
        exceeds_paid = (
            amount is not None
            and current.amount is not None
            and amount > current.amount
        )
        if exceeds_paid:
            msg = "A refund cannot exceed the amount paid."
            raise PaymentError(msg)

        refunded = PaymentResult(
            external_id=external_id,
            reference=current.reference,
            status=PaymentStatus.REFUNDED,
            amount=amount or current.amount,
            currency=current.currency,
            raw_response={"simulated": True, "partial": amount is not None},
        )
        self._payments[external_id] = refunded
        return refunded

    def parse_webhook(self, payload: dict, headers: dict[str, str]) -> PaymentResult:
        """Interpret a webhook shaped the way this simulator emits them.

        A real adapter verifies a signature header here. There is nothing to
        verify against, so this only checks the payload is well formed.
        """
        external_id = payload.get("external_id")
        raw_status = payload.get("status")
        if not external_id or not raw_status:
            msg = "Webhook payload must carry 'external_id' and 'status'."
            raise PaymentError(msg)

        try:
            status = PaymentStatus(raw_status)
        except ValueError as exc:
            msg = f"Unknown payment status: {raw_status!r}"
            raise PaymentError(msg) from exc

        current = self._get(external_id)
        updated = PaymentResult(
            external_id=external_id,
            reference=current.reference,
            status=status,
            amount=current.amount,
            currency=current.currency,
            paid_at=(
                datetime.now(UTC).isoformat() if status is PaymentStatus.PAID else None
            ),
            raw_response=dict(payload),
        )
        self._payments[external_id] = updated
        return updated

    # -- internals ----------------------------------------------------------

    def _get(self, external_id: str) -> PaymentResult:
        try:
            return self._payments[external_id]
        except KeyError as exc:
            msg = f"Unknown payment: {external_id}"
            raise PaymentError(msg) from exc
