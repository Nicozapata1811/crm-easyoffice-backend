"""Reactions to other apps' signals. Connected in DocumentosConfig.ready."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from crm_easyoffice.tramites.services import AVANZADA
from crm_easyoffice.tramites.services import nivel_firma

from .tasks import enviar_a_firma
from .tasks import generar_documento

if TYPE_CHECKING:
    from crm_easyoffice.tramites.models import Tramite


def al_requerir_documento(sender: type, tramite: Tramite, **kwargs: Any) -> None:
    # The signal is sent after the case's transaction commits.
    generar_documento.delay(tramite.pk)


def al_requerir_firma(sender: type, tramite: Tramite, **kwargs: Any) -> None:
    # Sent after the case's transaction commits. The assisted signature waits
    # for the executive's upload; only the advanced one goes to the provider.
    if nivel_firma(tramite.tipo) == AVANZADA:
        enviar_a_firma.delay(tramite.pk)
