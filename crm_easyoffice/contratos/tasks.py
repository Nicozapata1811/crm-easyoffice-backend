from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from .services import detectar_vencimientos

logger = logging.getLogger(__name__)


@shared_task
def detectar_vencimientos_diarios() -> int:
    """Create today's expiry alerts (HU-53). Celery Beat runs it every morning."""
    creadas = detectar_vencimientos(timezone.localdate())
    logger.info("Expiry detection created %s alerts.", creadas)
    return creadas
