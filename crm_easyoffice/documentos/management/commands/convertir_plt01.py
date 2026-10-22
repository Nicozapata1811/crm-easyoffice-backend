"""Convert an anonymised PLT-01 Word file into the docxtpl template.

    python manage.py convertir_plt01 [origen.docx] [destino.docx]

Kept for the documentation that cites it; ``convertir_plantilla PLT-01`` does
the same.
"""

from __future__ import annotations

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Convert PLT-01's merge fields into docxtpl tags."

    def add_arguments(self, parser) -> None:
        parser.add_argument("origen", nargs="?")
        parser.add_argument("destino", nargs="?")

    def handle(self, *args, origen: str, destino: str, **options) -> None:
        rutas = [ruta for ruta in (origen, destino) if ruta]
        call_command("convertir_plantilla", "PLT-01", *rutas, stdout=self.stdout)
