from typing import Any

from django.core.management.base import BaseCommand

from psc.identidad import normalizar_rut
from psc.models import IdentidadFicticia


class Command(BaseCommand):
    help = (
        "Add one fictitious identity to the registry. Never use a real person's data."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--rut", required=True)
        parser.add_argument("--serie", required=True)
        parser.add_argument("--nombre", required=True)

    def handle(self, *args: Any, **options: Any) -> None:
        IdentidadFicticia.objects.update_or_create(
            rut=normalizar_rut(options["rut"]),
            defaults={"numero_serie": options["serie"], "nombre": options["nombre"]},
        )
        self.stdout.write(self.style.SUCCESS("Fictitious identity saved."))
