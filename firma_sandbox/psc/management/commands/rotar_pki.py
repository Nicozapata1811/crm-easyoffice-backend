from typing import Any

from django.core.management.base import BaseCommand

from psc import pki


class Command(BaseCommand):
    help = (
        "Replace the issuing CA and the TSA, keeping the root, so earlier documents "
        "still validate. With --raiz, replace the root too. Restart the services "
        "afterwards."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--raiz",
            action="store_true",
            help="Also replace the root CA.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        pki.generar(conservar_raiz=not options["raiz"])
        alcance = (
            "root, issuing CA and TSA" if options["raiz"] else "issuing CA and TSA"
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Rotated the {alcance}. Restart firma-sandbox and its worker.",
            ),
        )
