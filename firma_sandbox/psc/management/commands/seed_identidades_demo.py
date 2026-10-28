import json
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand

from psc.identidad import normalizar_rut
from psc.models import IdentidadFicticia


class Command(BaseCommand):
    help = (
        "Load the fictitious civil registry the identity check reads "
        "(fixtures/identidades_demo.json)."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--archivo",
            default=str(settings.BASE_DIR / "fixtures" / "identidades_demo.json"),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        registros = json.loads(Path(options["archivo"]).read_text(encoding="utf-8"))
        for registro in registros:
            IdentidadFicticia.objects.update_or_create(
                rut=normalizar_rut(registro["rut"]),
                defaults={
                    "numero_serie": registro["numero_serie"],
                    "nombre": registro["nombre"],
                },
            )
        self.stdout.write(
            self.style.SUCCESS(f"{len(registros)} fictitious identities loaded."),
        )
