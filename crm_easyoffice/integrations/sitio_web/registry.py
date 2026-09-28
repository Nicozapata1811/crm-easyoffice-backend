"""Adapters by name, selected by the webhook's ``formato`` query parameter.

An Elementor adapter is only added once a real Elementor Pro webhook payload
has been captured; its shape is not guessed.
"""

from __future__ import annotations

from .base import SourceAdapter
from .base import UnknownAdapterError
from .generic import GenericAdapter

DEFAULT_ADAPTER = "generico"

ADAPTERS: dict[str, type[SourceAdapter]] = {
    "generico": GenericAdapter,
}


def get_adapter(name: str) -> SourceAdapter:
    """Return an instance of the adapter registered under ``name``.

    Raises:
        UnknownAdapterError: If nothing is registered under that name.
    """
    try:
        return ADAPTERS[name]()
    except KeyError as exc:
        msg = f"No inbound adapter named {name!r}."
        raise UnknownAdapterError(msg) from exc
