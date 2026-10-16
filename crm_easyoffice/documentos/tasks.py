from __future__ import annotations

from celery import shared_task

from crm_easyoffice.tramites.models import Tramite

from .services import generar


@shared_task
def generar_documento(tramite_id: int) -> None:
    """Generate a case's document; its state says what happened."""
    tramite = Tramite.objects.filter(pk=tramite_id).first()
    if tramite is not None:
        generar(tramite)
