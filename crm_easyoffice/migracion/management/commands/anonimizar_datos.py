"""Anonymize a throwaway copy of the database (scripts/staging/copy_local_db.sh)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from crm_easyoffice.migracion.anonimizacion import CopiaRechazadaError
from crm_easyoffice.migracion.anonimizacion import anonimizar
from crm_easyoffice.migracion.anonimizacion import exigir_copia
from crm_easyoffice.migracion.anonimizacion import plantillas_faltantes


class Command(BaseCommand):
    help = "Replace every personal value and private file of a copy, then verify it."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--es-copia",
            action="store_true",
            help="Confirm this database is a throwaway copy.",
        )
        parser.add_argument(
            "--identidades",
            help="Write the generated people here, for the test PSC's registry.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            exigir_copia(es_copia=options["es_copia"])
        except CopiaRechazadaError as error:
            raise CommandError(str(error)) from error

        faltan = plantillas_faltantes()
        if faltan:
            msg = f"Template files missing from the copy: {', '.join(faltan)}."
            raise CommandError(msg)

        try:
            resumen = anonimizar()
        except CopiaRechazadaError as error:
            raise CommandError(str(error)) from error

        if options["identidades"]:
            Path(options["identidades"]).write_text(
                json.dumps(resumen.identidades, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        if resumen.tablas_eliminadas:
            self.stdout.write(
                f"Dropped tables no model knows: "
                f"{', '.join(resumen.tablas_eliminadas)}.",
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Anonymized {resumen.personas} people, {resumen.empresas} companies, "
                f"{resumen.usuarios} users and {resumen.documentos} documents. "
                f"{resumen.valores_buscados} original values searched: none left.",
            ),
        )
