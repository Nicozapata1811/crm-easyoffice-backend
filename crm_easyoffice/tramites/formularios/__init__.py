"""Request forms of the documents implemented directly, one module per template.

The configurable engine is out of the MVP (team decision, 05-11-2026): each
of these documents has its own form here instead of a generic field engine.
A case type opts in with ``contrato: false`` in its configuration and is
matched by its ``plantilla`` code, never by its name.

Each module provides:

- ``Serializer``: the request's validation;
- ``guardar(cliente, datos)``: saves the parties and returns what the case
  keeps in ``Tramite.datos`` (people by id, never copied);
- ``prefill(cliente)``: what the client's own records already hold;
- ``valores(tramite)``: a saved case as the form's payload, for editing;
- ``resumen(tramite)``: label/value lines for the case screens;
- ``CLAVES_SENSIBLES`` and ``CLAVES_CONSERVADAS``: every ``datos`` path,
  classified for migracion.anonimizacion (replaced, or kept).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from . import plt03

if TYPE_CHECKING:
    from crm_easyoffice.tramites.models import TipoTramite

# Template code → form module. A new document adds its own.
FORMULARIOS: dict[str, Any] = {plt03.PLANTILLA: plt03}


def sin_contrato(tipo: TipoTramite) -> bool:
    """Whether the type's cases have no Contrato, folio or lines (``contrato``).

    True for documents between third parties (PLT-03 …): the case, its sale
    and its document are the record.
    """
    return tipo.configuracion.get("contrato", True) is False


def formulario_de(tipo: TipoTramite) -> Any | None:
    """The form module of a type without a contract, if its template has one."""
    if not sin_contrato(tipo):
        return None
    return FORMULARIOS.get(tipo.configuracion.get("plantilla", ""))
