"""Add fictitious warehouses and their owners so PLT-02 can be issued.

For local development and demos only. It runs seed_demo_domicilio first (the
branch and Easy Office's representative PLT-02 also prints), then creates
each warehouse only while no property holds its rol, so it never touches data
entered in the admin. Every name, RUT, address and image is invented.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import transaction

from crm_easyoffice.clientes.models import EstadoCivil
from crm_easyoffice.clientes.models import Persona
from crm_easyoffice.inmuebles.models import Autorizante
from crm_easyoffice.inmuebles.models import Oficina
from crm_easyoffice.inmuebles.models import TipoInmueble
from crm_easyoffice.inmuebles.services import guardar_documento_identidad

from .seed_demo_domicilio import DESDE
from .seed_demo_domicilio import rut
from .seed_demo_domicilio import tarjeta_png

# Fictitious rol → name, street, number, unit, comuna, region, and its owner.
BODEGAS = {
    "9001-001": (
        "Bodega de Ejemplo Norte",
        "Camino de Prueba",
        "500",
        "Bodega 1",
        "Quilicura",
        "Región Metropolitana de Santiago",
        (90_000_201, "Carolina Andrea", "Bodeguera", "Ejemplo", "Contadora"),
    ),
    "9001-002": (
        "Bodega de Ejemplo Costa",
        "Avenida Ficticia",
        "77",
        "Bodega 12",
        "Viña del Mar",
        "Región de Valparaíso",
        (90_000_202, "Pedro Pablo", "Almacén", "Ficticio", "Comerciante"),
    ),
}


class Command(BaseCommand):
    help = "Add demo warehouses with a natural-person owner, ready for PLT-02."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--force",
            action="store_true",
            help="Run even when DEBUG is off.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG and not options["force"]:
            msg = "Refusing to load demo data with DEBUG off; pass --force."
            raise CommandError(msg)

        call_command("seed_demo_domicilio", force=options["force"], stdout=self.stdout)
        with transaction.atomic():
            for rol, datos in BODEGAS.items():
                if not Oficina.objects.filter(rol_avaluo=rol).exists():
                    self._bodega(rol, datos)
                    self.stdout.write(f"Warehouse {rol} created.")
        self.stdout.write(self.style.SUCCESS("Demo warehouse data ready."))

    def _bodega(self, rol: str, datos: tuple[Any, ...]) -> None:
        nombre, calle, numero, unidad, comuna, region, dueno = datos
        bodega = Oficina.objects.create(
            tipo=TipoInmueble.BODEGA,
            rol_avaluo=rol,
            nombre=nombre,
            calle=calle,
            numero=numero,
            unidad=unidad,
            comuna=comuna,
            region=region,
        )
        numero_rut, nombres, paterno, materno, profesion = dueno
        persona, _ = Persona.objects.get_or_create(
            rut=rut(numero_rut),
            defaults={
                "nombres": nombres,
                "apellido_paterno": paterno,
                "apellido_materno": materno,
                "nacionalidad": "chilena",
                "estado_civil": EstadoCivil.SOLTERO,
                "profesion": profesion,
                "email": f"demo{numero_rut}@example.test",
            },
        )
        autorizante = Autorizante.objects.create(
            inmueble=bodega,
            persona=persona,
            vigente_desde=DESDE,
        )
        guardar_documento_identidad(
            autorizante,
            ContentFile(tarjeta_png(210), name="anverso.png"),
        )
        guardar_documento_identidad(
            autorizante,
            ContentFile(tarjeta_png(235), name="reverso.png"),
            reverso=True,
        )
