from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand

from psc import pki


class Command(BaseCommand):
    help = (
        "Generate the test PKI (root CA, issuing CA, TSA) into FIRMA_SANDBOX_PKI_DIR."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--si-falta",
            action="store_true",
            help="Do nothing when a PKI already exists (used on container start).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if pki.existe():
            if options["si_falta"]:
                self.stdout.write("Test PKI already present.")
                return
            self.stderr.write("A test PKI already exists; use rotar_pki to replace it.")
            return
        generada = pki.generar()
        self.stdout.write(
            self.style.SUCCESS(f"Test PKI generated in {settings.PKI_DIR}."),
        )
        self.stdout.write(f"Root: {generada.raiz.subject.rfc4514_string()}")
