"""Convert an anonymised PLT-01 Word file into the docxtpl template.

    python manage.py convertir_plt01 [origen.docx] [destino.docx]

Without arguments it rebuilds the committed seed (plantillas_semilla).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from crm_easyoffice.documentos.conversion.plt01 import convertir
from crm_easyoffice.documentos.semillas import ORIGEN_PLT01
from crm_easyoffice.documentos.semillas import PLANTILLA_PLT01


class Command(BaseCommand):
    help = "Convert PLT-01's merge fields into docxtpl tags."

    def add_arguments(self, parser) -> None:
        parser.add_argument("origen", nargs="?", default=str(ORIGEN_PLT01))
        parser.add_argument("destino", nargs="?", default=str(PLANTILLA_PLT01))

    def handle(self, *args, origen: str, destino: str, **options) -> None:
        try:
            convertido = convertir(Path(origen).read_bytes())
        except (OSError, ValueError, KeyError) as error:
            raise CommandError(str(error)) from error
        Path(destino).write_bytes(convertido)
        digest = hashlib.sha256(convertido).hexdigest()
        self.stdout.write(self.style.SUCCESS(f"{destino} sha256={digest}"))
