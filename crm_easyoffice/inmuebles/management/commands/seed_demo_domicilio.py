"""Complete the seeded branches with fictitious data so PLT-01 can be issued.

For local development and demos only. It fills a branch only while it still
holds the 0003 placeholders, and Easy Office's representative only while
none is set, so it never overwrites data entered in the admin. Every name,
RUT, address and image is invented.
"""

from __future__ import annotations

import struct
import zlib
from datetime import date
from typing import Any

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import transaction

from crm_easyoffice.clientes.models import Empresa
from crm_easyoffice.clientes.models import EstadoCivil
from crm_easyoffice.clientes.models import Persona
from crm_easyoffice.clientes.models import RepresentanteLegal
from crm_easyoffice.configuracion.models import ConfigEmpresa
from crm_easyoffice.core.validators import compute_rut_check_digit
from crm_easyoffice.inmuebles.models import Autorizante
from crm_easyoffice.inmuebles.models import Oficina
from crm_easyoffice.inmuebles.services import CALLE_PENDIENTE
from crm_easyoffice.inmuebles.services import guardar_documento_identidad

DESDE = date(2026, 1, 1)

# Branch code → fictitious street, number, unit, rol and SII unit.
SUCURSALES = {
    "LF": (
        "Avenida de Ejemplo",
        "1000",
        "Oficina 101",
        "0001-001",
        "UNIDAD DE EJEMPLO LF",
    ),
    "VL": ("Calle de Prueba", "200", "Oficina 202", "0002-002", "UNIDAD DE EJEMPLO VL"),
    "SA": ("Pasaje Ficticio", "30", "Local 3", "0003-003", "UNIDAD DE EJEMPLO SA"),
}


def rut(numero: int) -> str:
    return f"{numero}-{compute_rut_check_digit(str(numero))}"


def tarjeta_png(tono: int, ancho: int = 320, alto: int = 200) -> bytes:
    """A grey card-shaped PNG with a darker box: obviously not a real card."""

    def pixel(x: int, y: int) -> int:
        borde = x < 6 or y < 6 or x >= ancho - 6 or y >= alto - 6  # noqa: PLR2004
        foto = 20 <= x < 100 and 40 <= y < 160  # noqa: PLR2004
        return 60 if borde else 120 if foto else tono

    crudo = b"".join(
        b"\x00" + bytes(pixel(x, y) for x in range(ancho)) for y in range(alto)
    )

    def bloque(tipo: bytes, datos: bytes) -> bytes:
        cuerpo = tipo + datos
        return (
            struct.pack(">I", len(datos))
            + cuerpo
            + struct.pack(">I", zlib.crc32(cuerpo))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + bloque(b"IHDR", struct.pack(">IIBBBBB", ancho, alto, 8, 0, 0, 0, 0))
        + bloque(b"IDAT", zlib.compress(crudo))
        + bloque(b"IEND", b"")
    )


class Command(BaseCommand):
    help = "Fill the seeded branches and Easy Office's representative with demo data."

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

        with transaction.atomic():
            config = ConfigEmpresa.objects.first()
            if config is not None and config.representante is None:
                config.representante = self._persona(
                    90_000_001,
                    "Rodrigo Andrés",
                    "Ejemplo",
                    "Ficticio",
                    "Ingeniero comercial",
                )
                config.save(update_fields=["representante", "updated_at"])
                self.stdout.write("Easy Office representative set.")

            for indice, (codigo, datos) in enumerate(SUCURSALES.items(), start=1):
                oficina = Oficina.objects.filter(
                    codigo_sucursal=codigo,
                    calle=CALLE_PENDIENTE,
                ).first()
                if oficina is not None:
                    self._sucursal(oficina, indice, datos)
                    self.stdout.write(f"Branch {codigo} completed.")

        self.stdout.write(self.style.SUCCESS("Demo domicile data ready."))

    def _persona(
        self,
        numero: int,
        nombres: str,
        paterno: str,
        materno: str,
        profesion: str,
    ) -> Persona:
        persona, _ = Persona.objects.get_or_create(
            rut=rut(numero),
            defaults={
                "nombres": nombres,
                "apellido_paterno": paterno,
                "apellido_materno": materno,
                "nacionalidad": "chilena",
                "estado_civil": EstadoCivil.CASADO,
                "profesion": profesion,
                "email": f"demo{numero}@example.test",
            },
        )
        return persona

    def _sucursal(self, oficina: Oficina, indice: int, datos: tuple[str, ...]) -> None:
        calle, numero, unidad, rol, unidad_sii = datos
        oficina.calle = calle
        oficina.numero = numero
        oficina.unidad = unidad
        oficina.rol_avaluo = rol
        oficina.unidad_sii = unidad_sii
        oficina.municipalidad = oficina.comuna
        oficina.save()

        empresa, _ = Empresa.objects.get_or_create(
            rut=rut(76_900_000 + indice),
            defaults={"razon_social": f"Inmobiliaria de Ejemplo {indice} Ltda."},
        )
        persona = self._persona(
            90_000_100 + indice,
            "María José",
            "Propietaria",
            f"Ejemplo {indice}",
            "Abogada",
        )
        representante, _ = RepresentanteLegal.objects.get_or_create(
            persona=persona,
            empresa=empresa,
            defaults={"vigente_desde": DESDE},
        )
        autorizante = Autorizante.objects.create(
            inmueble=oficina,
            empresa=empresa,
            representante=representante,
            vigente_desde=DESDE,
        )
        guardar_documento_identidad(
            autorizante,
            ContentFile(tarjeta_png(200), name="anverso.png"),
        )
        guardar_documento_identidad(
            autorizante,
            ContentFile(tarjeta_png(225), name="reverso.png"),
            reverso=True,
        )
