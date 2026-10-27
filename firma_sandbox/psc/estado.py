"""The public view of a signing request: what the API and the webhooks show.

Only names and states leave the service; RUTs and emails stay inside.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from datetime import datetime

    from .models import Firmante
    from .models import Solicitud

AMBIENTE = "pruebas"


def _fecha(valor: datetime | None) -> str | None:
    return valor.isoformat() if valor else None


def estado_firmante(firmante: Firmante) -> dict[str, Any]:
    return {
        "id": str(firmante.id),
        "orden": firmante.orden,
        "nombre": firmante.nombre,
        "rol": firmante.rol,
        "referencia": firmante.referencia,
        "estado": firmante.estado,
        "firmado_en": _fecha(firmante.firmado_en),
        "rechazado_en": _fecha(firmante.rechazado_en),
        "motivo_rechazo": firmante.motivo_rechazo,
    }


def estado_solicitud(solicitud: Solicitud) -> dict[str, Any]:
    return {
        "id": str(solicitud.id),
        "estado": solicitud.estado,
        "ambiente": AMBIENTE,
        "nombre_documento": solicitud.nombre_documento,
        "referencia_externa": solicitud.referencia_externa,
        "creada_en": _fecha(solicitud.creada_en),
        "expira_en": _fecha(solicitud.expira_en),
        "terminada_en": _fecha(solicitud.terminada_en),
        "sha256_original": solicitud.sha256_original,
        "sha256_firmado": solicitud.sha256_firmado or None,
        "firmantes": [
            estado_firmante(f) for f in solicitud.firmantes.order_by("orden")
        ],
    }
