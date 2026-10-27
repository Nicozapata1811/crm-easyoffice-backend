import os
import secrets
from typing import Any

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from psc.models import ClienteApi
from psc.models import resumen


class Command(BaseCommand):
    help = (
        "Create or update an API client. --desde-env reads the CRM's local credentials."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--nombre", default="crm-local")
        parser.add_argument(
            "--desde-env",
            action="store_true",
            help=(
                "Take the key and webhook secret from SIGNATURE_API_KEY and "
                "SIGNATURE_WEBHOOK_SECRET."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["desde_env"]:
            clave = os.environ.get("SIGNATURE_API_KEY", "")
            secreto = os.environ.get("SIGNATURE_WEBHOOK_SECRET", "")
            if not clave or not secreto:
                msg = (
                    "Set SIGNATURE_API_KEY and SIGNATURE_WEBHOOK_SECRET "
                    "(see .envs.example/.local/.firma)."
                )
                raise CommandError(msg)
        else:
            clave = secrets.token_urlsafe(32)
            secreto = secrets.token_urlsafe(32)
        ClienteApi.objects.update_or_create(
            nombre=options["nombre"],
            defaults={
                "hash_api_key": resumen(clave),
                "secreto_webhook": secreto,
                "activo": True,
            },
        )
        self.stdout.write(
            self.style.SUCCESS(f"API client {options['nombre']!r} ready."),
        )
        if not options["desde_env"]:
            # Shown once; only the hash is kept.
            self.stdout.write(f"API key: {clave}\nWebhook secret: {secreto}")
