"""Switch the case types to the advanced signature, for a local demo (IN-01).

For local development and demos only, with the test PSC running
(``docker compose --profile firma up``). Its signatures have no legal
validity. It runs seed_demo_bodega first, so the branches, the warehouses
and Easy Office's representative exist; their fictitious RUTs are in the test
PSC's fictitious registry (firma_sandbox/fixtures/identidades_demo.json).
``--asistida`` puts both types back on the assisted signature.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from crm_easyoffice.tramites.models import TipoTramite

# ASSUMPTION: pending validation with Easy Office. Who signs and in what
# order (RN-39), whether Easy Office signs every contract (ACTA-002 D2-03)
# and whether the authoriser signs through the provider or unattended.
FIRMANTES = ["cliente_representante", "representante_emisor", "autorizante"]

# Fictitious people the test PSC knows, free to type in the case form as the
# client's representative (one company each; 90000301-3 is the e2e test's).
REPRESENTANTES_DEMO = ["90000302-1", "90000303-K", "90000304-8", "90000305-6"]


class Command(BaseCommand):
    help = "Use the advanced signature (test PSC) for every case type. DEBUG only."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--asistida",
            action="store_true",
            help="Go back to the assisted signature.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Run even when DEBUG is off.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG and not options["force"]:
            msg = "Refusing to load demo data with DEBUG off; pass --force."
            raise CommandError(msg)

        if options["asistida"]:
            firma = {"nivel": "asistida"}
        else:
            call_command("seed_demo_bodega", force=options["force"], stdout=self.stdout)
            firma = {"nivel": "avanzada", "firmantes": FIRMANTES}
        for tipo in TipoTramite.objects.all():
            tipo.configuracion["firma"] = firma
            tipo.save(update_fields=["configuracion", "updated_at"])
            self.stdout.write(f"{tipo.nombre}: firma {firma['nivel']}.")

        if not options["asistida"]:
            self.stdout.write(
                self.style.SUCCESS(
                    "Advanced signature on.\n"
                    "Client's representative RUT: one of "
                    f"{', '.join(REPRESENTANTES_DEMO)} (any other fictitious one "
                    "must be added to the test PSC with registrar_identidad). "
                    "The ID-card serial of each demo person is 'A' followed by "
                    "the RUT's number, e.g. A90000302. "
                    "Codes and links arrive in Mailpit, http://localhost:8025.",
                ),
            )
