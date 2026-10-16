from __future__ import annotations

from pathlib import Path

import pytest

from crm_easyoffice.core.storage import private_storage
from crm_easyoffice.documentos.models import VersionPlantilla
from crm_easyoffice.documentos.semillas import PLANTILLA_PLT01


@pytest.fixture(autouse=True)
def _plantilla_en_almacenamiento(db, _media_storage) -> None:
    """Each test has its own private storage; put the seeded template back."""
    for version in VersionPlantilla.objects.all():
        destino = Path(private_storage.path(version.archivo.name))
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(PLANTILLA_PLT01.read_bytes())
