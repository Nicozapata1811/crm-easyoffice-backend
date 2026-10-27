import logging
import time
from typing import Any

from django.core.management.base import BaseCommand

from psc import servicios
from psc import webhooks

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Deliver due webhooks and expire overdue requests, in a loop (the worker)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--una-vez",
            action="store_true",
            help="Run one round and exit.",
        )
        parser.add_argument(
            "--cada",
            type=float,
            default=2.0,
            help="Seconds between rounds.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        while True:
            vencidas = servicios.expirar_vencidas()
            entregadas = webhooks.entregar_pendientes()
            if vencidas or entregadas:
                logger.info(
                    "Expired %s requests, delivered %s webhooks.",
                    vencidas,
                    entregadas,
                )
            if options["una_vez"]:
                return
            time.sleep(options["cada"])
