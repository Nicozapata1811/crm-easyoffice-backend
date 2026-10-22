from __future__ import annotations

from pathlib import Path

import pytest

from crm_easyoffice.core.storage import private_storage
from crm_easyoffice.documentos.models import VersionPlantilla
from crm_easyoffice.documentos.semillas import PLANTILLAS


@pytest.fixture(autouse=True)
def _plantilla_en_almacenamiento(db, _media_storage) -> None:
    """Each test has its own private storage; put the seeded templates back."""
    for version in VersionPlantilla.objects.select_related("plantilla"):
        destino = Path(private_storage.path(version.archivo.name))
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(PLANTILLAS[version.plantilla.codigo].read_bytes())
