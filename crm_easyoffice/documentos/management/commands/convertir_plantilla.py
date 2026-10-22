"""Convert an anonymised template (PLT-01, PLT-02) into its docxtpl template.

    python manage.py convertir_plantilla PLT-02 [origen.docx] [destino.docx]

Without paths it rebuilds the committed seed (plantillas_semilla).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from crm_easyoffice.documentos.conversion import plt01
from crm_easyoffice.documentos.conversion import plt02
from crm_easyoffice.documentos.semillas import ORIGEN_PLT01
from crm_easyoffice.documentos.semillas import ORIGEN_PLT02
from crm_easyoffice.documentos.semillas import PLANTILLA_PLT01
from crm_easyoffice.documentos.semillas import PLANTILLA_PLT02

# Template code → converter, committed origin, committed conversion.
CONVERSORES = {
    "PLT-01": (plt01.convertir, ORIGEN_PLT01, PLANTILLA_PLT01),
    "PLT-02": (plt02.convertir, ORIGEN_PLT02, PLANTILLA_PLT02),
}


class Command(BaseCommand):
    help = "Convert a template's merge fields and markers into docxtpl tags."

    def add_arguments(self, parser) -> None:
        parser.add_argument("codigo", choices=sorted(CONVERSORES))
        parser.add_argument("origen", nargs="?")
        parser.add_argument("destino", nargs="?")

    def handle(self, *args, codigo: str, origen: str, destino: str, **options) -> None:
        convertir, origen_semilla, destino_semilla = CONVERSORES[codigo]
        origen = origen or str(origen_semilla)
        destino = destino or str(destino_semilla)
        try:
            convertido = convertir(Path(origen).read_bytes())
        except (OSError, ValueError, KeyError) as error:
            raise CommandError(str(error)) from error
        Path(destino).write_bytes(convertido)
        digest = hashlib.sha256(convertido).hexdigest()
        self.stdout.write(self.style.SUCCESS(f"{destino} sha256={digest}"))
