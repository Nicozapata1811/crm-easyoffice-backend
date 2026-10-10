"""The payment provider contract.

The company has not chosen a provider. Transbank and Mercado Pago were both
mentioned; Transbank in its integration environment is the reference this
contract is shaped against.

ASSUMPTION: pending validation with Easy Office. Which services require payment
at all, and whether payment is taken before or after a case advances, are open
questions. This contract deliberately says nothing about either.
"""

from __future__ import annotations

import enum
from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from decimal import Decimal


class PaymentStatus(enum.StrEnum):
    """Lifecycle of a payment, as this project models it.

    The adapter maps the provider's own vocabulary onto these values.
    """

    PENDING = "pending"
    AUTHORIZED = "authorized"
    PAID = "paid"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REFUNDED = "refunded"
    FAILED = "failed"


PAYMENT_DETAIL_KEYS = (
    "method",
    "brand",
    "card_type",
    "last_digits",
    "installments",
    "wallet",
)


@dataclass(frozen=True)
class Payer:
    email: str
    rut: str = ""
    first_name: str = ""
    last_name: str = ""


@dataclass(frozen=True)
class PaymentItem:
    code: str
    name: str
    unit_price: Decimal
    quantity: int = 1


@dataclass(frozen=True)
class PaymentRequest:
    """What the domain hands the provider to start a payment.

    ``reference`` is this project's own identifier for the payment and is what
    the provider is asked to echo back, so a returning user or a duplicated
    webhook can be reconciled against it.
    """

    reference: str
    amount: Decimal
    currency: str = "CLP"
    description: str = ""
    return_url: str | None = None
    cancel_url: str | None = None
    notification_url: str | None = None
    payer: Payer | None = None
    items: tuple[PaymentItem, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PaymentResult:
    """What the provider hands back.

    ``redirect_url`` carries the hosted payment page where one applies. This
    project never handles card details itself; ``details`` only holds what the
    provider reports about the payment, with the keys in ``PAYMENT_DETAIL_KEYS``.
    """

    external_id: str
    reference: str
    status: PaymentStatus
    amount: Decimal | None = None
    currency: str = "CLP"
    redirect_url: str | None = None
    authorization_code: str | None = None
    paid_at: str | None = None
    details: dict[str, str] = field(default_factory=dict)
    raw_response: dict = field(default_factory=dict)


class PaymentError(Exception):
    """Raised when a payment operation cannot be completed.

    ``transient`` marks failures worth retrying, such as a timeout or a 5xx.
    """

    def __init__(self, message: str = "", *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


class PaymentProvider(ABC):
    """Contract every payment provider implementation satisfies.

    Implementations must not leak provider-specific types across this
    boundary, and no provider SDK is imported outside this app.
    """

    @abstractmethod
    def create_payment(self, request: PaymentRequest) -> PaymentResult:
        """Start a payment and return its initial state."""

    @abstractmethod
    def get_status(self, external_id: str) -> PaymentResult:
        """Return the current state of an existing payment."""

    @abstractmethod
    def confirm(self, external_id: str) -> PaymentResult:
        """Confirm a payment the user has returned from.

        Providers that require an explicit commit step do it here. This must be
        safe to call more than once for the same payment.
        """

    @abstractmethod
    def refund(self, external_id: str, amount: Decimal | None = None) -> PaymentResult:
        """Refund a payment in full, or partially when ``amount`` is given."""

    @abstractmethod
    def parse_webhook(
        self,
        payload: dict,
        headers: dict[str, str],
        *,
        event: str | None = None,
    ) -> PaymentResult:
        """Translate a provider webhook into a ``PaymentResult``.

        ``event`` names the notification when the provider tells them apart by
        URL rather than in the payload.

        Implementations are responsible for verifying authenticity. Callers are
        responsible for idempotency: the same event may arrive more than once
        and events may arrive out of order.
        """
