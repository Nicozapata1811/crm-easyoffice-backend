"""Load fictitious clients for local development and demos.

Every name, RUT, email and phone number is generated. Each client draws from
its own seeded generator, so running the command again creates nothing new.
"""

from __future__ import annotations

import random
import unicodedata
from datetime import datetime
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone

from crm_easyoffice.clientes.models import Cliente
from crm_easyoffice.clientes.models import Empresa
from crm_easyoffice.clientes.models import Persona
from crm_easyoffice.clientes.models import RepresentanteLegal
from crm_easyoffice.core.validators import compute_rut_check_digit

NOMBRES = [
    "Camila",
    "Matías",
    "Valentina",
    "Benjamín",
    "Antonia",
    "Vicente",
    "Florencia",
    "Tomás",
    "Javiera",
    "Joaquín",
    "Catalina",
    "Agustín",
]
APELLIDOS = [
    "Soto",
    "Muñoz",
    "Rojas",
    "Díaz",
    "Contreras",
    "Silva",
    "Morales",
    "Fuentes",
    "Valenzuela",
    "Araya",
    "Tapia",
    "Reyes",
]
RUBROS = [
    ("Asesorías", "Asesoría empresarial"),
    ("Comercial", "Venta al por menor"),
    ("Construcciones", "Construcción de obras menores"),
    ("Servicios Digitales", "Desarrollo de software"),
    ("Transportes", "Transporte de carga por carretera"),
    ("Gastronomía", "Servicio de comida preparada"),
]
LUGARES = ["Andes", "Pacífico", "Austral", "del Valle", "Cordillera", "Litoral"]
DIAS_ATRAS = 365
UNA_EMPRESA_CADA = 3
PROPORCION_INACTIVOS = 0.1
PROPORCION_CON_REPRESENTANTE = 0.7


def build_rut(number: int) -> str:
    return f"{number}-{compute_rut_check_digit(str(number))}"


def ascii_slug(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return plain.lower().replace(" ", "")


class Command(BaseCommand):
    help = "Create fictitious clients (personas and empresas) for development."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--cantidad", type=int, default=40)
        parser.add_argument("--semilla", type=int, default=2026)
        parser.add_argument(
            "--force",
            action="store_true",
            help="Run even when DEBUG is off.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG and not options["force"]:
            msg = "Refusing to load demo data with DEBUG off; pass --force."
            raise CommandError(msg)

        now = timezone.now()
        creados = 0
        with transaction.atomic():
            for indice in range(options["cantidad"]):
                rng = random.Random(f"{options['semilla']}:{indice}")  # noqa: S311
                es_empresa = indice % UNA_EMPRESA_CADA == UNA_EMPRESA_CADA - 1
                parte = (
                    self._empresa(rng, indice, now)
                    if es_empresa
                    else self._persona(rng, indice)
                )
                if parte is None:
                    continue
                cliente = Cliente.objects.create(
                    **{"empresa" if es_empresa else "persona": parte},
                    activo=rng.random() >= PROPORCION_INACTIVOS,
                )
                registrado = now - timedelta(days=rng.randrange(DIAS_ATRAS))
                Cliente.objects.filter(pk=cliente.pk).update(created_at=registrado)
                creados += 1

        self.stdout.write(self.style.SUCCESS(f"Created {creados} demo clients."))

    def _persona(self, rng: random.Random, indice: int) -> Persona | None:
        rut = build_rut(rng.randrange(10_000_000, 25_000_000))
        if Persona.objects.filter(rut=rut).exists():
            return None
        nombre = rng.choice(NOMBRES)
        paterno, materno = rng.sample(APELLIDOS, 2)
        return Persona.objects.create(
            rut=rut,
            nombres=nombre,
            apellido_paterno=paterno,
            apellido_materno=materno,
            email=f"{ascii_slug(nombre)}.{ascii_slug(paterno)}{indice}@example.test",
            telefono=f"+56 9 0000 {indice:04d}",
        )

    def _empresa(
        self,
        rng: random.Random,
        indice: int,
        now: datetime,
    ) -> Empresa | None:
        rut = build_rut(rng.randrange(76_000_000, 78_000_000))
        if Empresa.objects.filter(rut=rut).exists():
            return None
        rubro, giro = rng.choice(RUBROS)
        lugar = rng.choice(LUGARES)
        empresa = Empresa.objects.create(
            rut=rut,
            razon_social=f"{rubro} {lugar} de Ejemplo SpA",
            nombre_fantasia=f"{rubro} {lugar}",
            giro=giro,
            email=f"contacto{indice}@{ascii_slug(rubro)}.example.test",
            telefono=f"+56 2 0000 {indice:04d}",
        )
        if rng.random() < PROPORCION_CON_REPRESENTANTE:
            representante = self._persona(rng, 1000 + indice)
            if representante is not None:
                RepresentanteLegal.objects.create(
                    persona=representante,
                    empresa=empresa,
                    vigente_desde=(now - timedelta(days=rng.randrange(30, 900))).date(),
                )
        return empresa
