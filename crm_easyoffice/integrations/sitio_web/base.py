"""The inbound source adapter contract and the canonical lead shape."""

from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

CANONICAL_FIELDS = (
    "nombre",
    "email",
    "telefono",
    "servicio_interes",
    "plan",
    "origen",
    "mensaje",
    "id_envio",
)


@dataclass(frozen=True)
class ProspectoEntrante:
    """A validated lead as received from any source.

    ``id_envio`` is the source's own submission id, when it provides one, and
    is used only for de-duplication.
    """

    nombre: str
    email: str
    telefono: str
    servicio_interes: str
    plan: str
    origen: str
    mensaje: str
    recibido_en: datetime
    payload_original: dict[str, Any] = field(default_factory=dict)
    id_envio: str = ""


class UnknownAdapterError(LookupError):
    """Raised when no adapter is registered under the requested name."""


class SourceAdapter(ABC):
    """Contract every inbound source adapter satisfies."""

    @abstractmethod
    def parse(self, data: Mapping[str, Any]) -> dict[str, Any]:
        """Map a source payload onto ``CANONICAL_FIELDS``.

        Only renames and restructures. Absent fields are left out rather than
        defaulted, and unknown fields are dropped. Validation happens after
        this, identically for every source.
        """
