"""Helpers for document tests. Every value they produce is synthetic."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from crm_easyoffice.documentos.models import Documento
from crm_easyoffice.documentos.models import VersionPlantilla

if TYPE_CHECKING:
    from datetime import datetime

    from crm_easyoffice.tramites.models import Tramite

HASH_FICTICIO = "0" * 64


def documento_generado(
    tramite: Tramite,
    version: int,
    generado_en: datetime,
    **campos: Any,
) -> Documento:
    """A document row on the seeded PLT-01 version, without rendering any file."""
    return Documento.objects.create(
        tramite=tramite,
        version=version,
        version_plantilla=VersionPlantilla.objects.get(
            plantilla__codigo="PLT-01",
            numero=1,
        ),
        archivo_docx=f"prueba/{tramite.pk}-v{version}.docx",
        sha256_docx=HASH_FICTICIO,
        archivo_pdf=f"prueba/{tramite.pk}-v{version}.pdf",
        sha256_pdf=HASH_FICTICIO,
        datos_snapshot={},
        generado_en=generado_en,
        **campos,
    )
