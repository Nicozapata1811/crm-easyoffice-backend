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


@dataclass(frozen=True)
class SignatureRequest:
    """What the domain hands the provider to start a signature process."""

    document_id: str
    document_name: str
    content: bytes
    signers: list[Signer]
    callback_url: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


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


class SignatureError(Exception):
    """Raised when a signature operation cannot be completed."""


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
    def parse_webhook(self, payload: dict, headers: dict[str, str]) -> SignatureResult:
        """Translate a provider webhook into a ``SignatureResult``.

        Implementations are responsible for verifying authenticity. Callers are
        responsible for idempotency: the same event may arrive more than once
        and events may arrive out of order.
        """
