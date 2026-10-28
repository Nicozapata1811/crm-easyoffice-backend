"""The signature provider contract.

The company's provider is tufirma.digital. Its credentials have been requested
but are not available yet, and its API details are unknown, so this contract is
derived from what the counterpart has stated about the process rather than from
any provider documentation.

Everything here is intentionally provider-agnostic. When the real credentials
arrive, a second implementation of ``SignatureProvider`` drops in behind the
same interface and nothing in the domain changes.
"""

from __future__ import annotations

import enum
from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from dataclasses import field


class SignerState(enum.StrEnum):
    """Where one signer stands."""

    PENDING = "pending"
    SIGNED = "signed"
    DECLINED = "declined"


class SignatureEventType(enum.StrEnum):
    """What a provider notifies. The adapter maps the provider's names."""

    SIGNER_SIGNED = "signer_signed"
    SIGNER_DECLINED = "signer_declined"
    COMPLETED = "completed"
    EXPIRED = "expired"


class SignatureStatus(enum.StrEnum):
    """Lifecycle of a signature request, as this project models it.

    ASSUMPTION: pending validation with Easy Office. The provider's own status
    vocabulary is unknown; these are the states the process needs, and the
    adapter is responsible for mapping the provider's values onto them.
    """

    PENDING = "pending"
    PARTIALLY_SIGNED = "partially_signed"
    SIGNED = "signed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    FAILED = "failed"


@dataclass(frozen=True)
class Signer:
    """One party required to sign a document.

    Multiple signers per document are an explicit requirement from the
    counterpart, so this is always handled as a collection.
    """

    full_name: str
    email: str
    rut: str | None = None
    order: int = 0
    role: str = ""
    # Our own id for this signer; the provider echoes it back in each status.
    reference: str = ""


@dataclass(frozen=True)
class SignerStatus:
    """One signer's state, as the provider reports it."""

    reference: str
    external_id: str
    order: int
    status: SignerState
    signed_at: str | None = None
    declined_at: str | None = None
    declined_reason: str = ""


@dataclass(frozen=True)
class SignatureRequest:
    """What the domain hands the provider to start a signature process."""

    document_id: str
    document_name: str
    content: bytes
    signers: list[Signer]
    callback_url: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)
    expires_at: str | None = None


@dataclass(frozen=True)
class SignatureResult:
    """What the provider hands back.

    ``external_id`` is the provider's own identifier. It is what makes webhook
    handling idempotent: events arrive duplicated and out of order, and this is
    the key they are reconciled against.
    """

    external_id: str
    status: SignatureStatus
    signed_content: bytes | None = None
    signed_hash: str | None = None
    signed_at: str | None = None
    raw_response: dict = field(default_factory=dict)
    signers: list[SignerStatus] = field(default_factory=list)
    # SHA-256 of the document the provider received, as it reports it. The
    # domain checks it against what it sent (RF-39).
    original_sha256: str | None = None
    # The provider says it is a test environment: its signatures have no
    # legal validity.
    test_environment: bool = False


@dataclass(frozen=True)
class SignatureEvent:
    """A verified webhook. ``event_id`` is what duplicates are detected by."""

    event_id: str
    type: SignatureEventType
    result: SignatureResult


class SignatureError(Exception):
    """Raised when a signature operation cannot be completed.

    ``transient`` marks failures worth retrying (timeouts, 5xx), as in
    ``PaymentError``.
    """

    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


class SignatureProvider(ABC):
    """Contract every signature provider implementation satisfies.

    Implementations must not leak provider-specific types across this
    boundary, and no provider SDK is imported outside this app.
    """

    @abstractmethod
    def create_request(self, request: SignatureRequest) -> SignatureResult:
        """Start a signature process and return its initial state."""

    @abstractmethod
    def get_status(self, external_id: str) -> SignatureResult:
        """Return the current state of an existing signature process."""

    @abstractmethod
    def download_signed(self, external_id: str) -> bytes:
        """Return the signed file.

        Raises ``SignatureError`` if the process has not completed.
        """

    @abstractmethod
    def cancel(self, external_id: str) -> SignatureResult:
        """Cancel a signature process that has not completed."""

    @abstractmethod
    def resend(self, external_id: str, signer_external_id: str) -> None:
        """Send a pending signer a new link; the previous one stops working."""

    @abstractmethod
    def parse_webhook(self, body: bytes, headers: dict[str, str]) -> SignatureEvent:
        """Verify a provider webhook and translate it into a ``SignatureEvent``.

        It takes the raw body because authenticity is checked over the exact
        bytes received. Callers are responsible for idempotency: the same
        event may arrive more than once and events may arrive out of order.
        """
