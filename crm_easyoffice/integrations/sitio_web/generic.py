"""The generic flat format, documented in docs/integration/website-contract.md."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from .base import SourceAdapter

if TYPE_CHECKING:
    from collections.abc import Mapping

FIELD_MAP = {
    "nombre": "nombre",
    "email": "email",
    "telefono": "telefono",
    "servicio": "servicio_interes",
    "plan": "plan",
    "origen": "origen",
    "mensaje": "mensaje",
    "id_envio": "id_envio",
}


class GenericAdapter(SourceAdapter):
    """Flat key/value payload, the same across form-encoded, multipart and JSON."""

    def parse(self, data: Mapping[str, Any]) -> dict[str, Any]:
        return {
            canonical: data.get(source)
            for source, canonical in FIELD_MAP.items()
            if source in data
        }
