"""Recording leads, idempotently."""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

from django.db import IntegrityError
from django.db import transaction
from django.utils import timezone

from crm_easyoffice.tramites.catalogo import buscar_plan
from crm_easyoffice.tramites.catalogo import buscar_servicio

from .models import Prospecto

if TYPE_CHECKING:
    from crm_easyoffice.integrations.sitio_web.base import ProspectoEntrante

logger = logging.getLogger(__name__)


def calcular_dedup_key(entrante: ProspectoEntrante, formato: str) -> str:
    """Key under which resubmissions of the same lead collapse into one.

    The source's submission id wins when present. Otherwise identical content
    received on the same local day is the same lead.

    ASSUMPTION: pending validation with Easy Office. The one-day window.
    """
    if entrante.id_envio:
        partes = [formato, "id_envio", entrante.id_envio]
    else:
        partes = [
            formato,
            entrante.email.lower(),
            "".join(c for c in entrante.telefono if c.isdigit()),
            entrante.servicio_interes,
            entrante.plan,
            " ".join(entrante.mensaje.split()).lower(),
            timezone.localdate(entrante.recibido_en).isoformat(),
        ]
    return hashlib.sha256("\x1f".join(partes).encode()).hexdigest()


def registrar_prospecto(
    entrante: ProspectoEntrante,
    *,
    formato: str,
) -> tuple[Prospecto, bool]:
    """Store a lead unless it was already recorded.

    Returns:
        The prospecto, and whether it was created by this call.
    """
    dedup_key = calcular_dedup_key(entrante, formato)
    existente = Prospecto.objects.filter(dedup_key=dedup_key).first()
    if existente is not None:
        logger.info("Duplicate submission ignored for prospecto %s", existente.pk)
        return existente, False

    servicio = entrante.servicio_interes
    plan = entrante.plan
    try:
        with transaction.atomic():
            prospecto = Prospecto.objects.create(
                formato=formato,
                origen=entrante.origen,
                nombre=entrante.nombre,
                email=entrante.email,
                telefono=entrante.telefono,
                servicio_interes=servicio,
                plan=plan,
                servicio_desconocido=bool(servicio) and not buscar_servicio(servicio),
                plan_desconocido=bool(plan) and not buscar_plan(servicio, plan),
                mensaje=entrante.mensaje,
                recibido_en=entrante.recibido_en,
                payload_original=entrante.payload_original,
                dedup_key=dedup_key,
            )
    except IntegrityError:
        return Prospecto.objects.get(dedup_key=dedup_key), False

    logger.info("Prospecto %s recorded from %s", prospecto.pk, formato)
    return prospecto, True
