"""Reactions to other apps' signals. Connected in DocumentosConfig.ready."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from .tasks import generar_documento

if TYPE_CHECKING:
    from crm_easyoffice.tramites.models import Tramite


def al_requerir_documento(sender: type, tramite: Tramite, **kwargs: Any) -> None:
    # The signal is sent after the case's transaction commits.
    generar_documento.delay(tramite.pk)
