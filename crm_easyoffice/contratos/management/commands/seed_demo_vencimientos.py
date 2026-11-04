"""Load contracts about to expire, so the alerts can be shown (EVI-T14).

For local development and staging only. Every company and RUT is invented.
It needs seed_demo_usuarios first. Running it again moves the same contracts'
dates to today instead of using up folios; it creates no alert itself, the
detection task does.
"""

from __future__ import annotations

from datetime import date
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone

from crm_easyoffice.clientes.models import Cliente
from crm_easyoffice.clientes.models import Empresa
from crm_easyoffice.configuracion.models import Marca
from crm_easyoffice.contratos.models import Contrato
from crm_easyoffice.contratos.services import LineaContrato
from crm_easyoffice.contratos.services import calcular_vencimiento
from crm_easyoffice.contratos.services import crear_contrato
from crm_easyoffice.core.validators import compute_rut_check_digit
from crm_easyoffice.inmuebles.models import Oficina
from crm_easyoffice.ventas.models import Servicio

EJECUTIVO = "ejecutivo@example.test"
ADMINISTRADOR = "admin@example.test"
MESES = 12

# Days to expiry, the fictitious company's RUT number, and who is responsible.
# The Administrador's lets the Ejecutivo prove they do not see another's alert.
DEMOS = [
    (5, 76_950_105, EJECUTIVO),
    (14, 76_950_114, EJECUTIVO),
    (29, 76_950_129, ADMINISTRADOR),
    (59, 76_950_159, None),
]


def inicio_para(vencimiento: date) -> date:
    """A start that gives a 12-month term ending about on ``vencimiento``.

    On a 29 February the term ends one day early, which crosses no threshold of
    the demo.
    """
    siguiente = vencimiento + timedelta(days=1)
    if (siguiente.month, siguiente.day) == (2, 29):
        siguiente = siguiente.replace(day=28)
    return siguiente.replace(year=siguiente.year - 1)


class Command(BaseCommand):
    help = "Load demo contracts about to expire. DEBUG only, unless --force."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--force",
            action="store_true",
            help="Run even when DEBUG is off (staging). Never in production.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if "production" in (settings.SETTINGS_MODULE or ""):
            msg = "Refusing to load demo data with production settings."
            raise CommandError(msg)
        if not settings.DEBUG and not options["force"]:
            msg = "Refusing to load demo data with DEBUG off; pass --force."
            raise CommandError(msg)

        usuarios = self._usuarios()
        hoy = timezone.localdate()
        try:
            with transaction.atomic():
                for dias, numero, responsable in DEMOS:
                    contrato = self._contrato(
                        hoy + timedelta(days=dias),
                        numero,
                        usuarios.get(responsable),
                    )
                    self.stdout.write(
                        f"{contrato.folio}: expires {contrato.fecha_vencimiento}.",
                    )
        except ValidationError as error:
            raise CommandError("; ".join(error.messages)) from error
        self.stdout.write(self.style.SUCCESS("Demo contracts ready."))

    def _usuarios(self) -> dict[str, Any]:
        correos = [EJECUTIVO, ADMINISTRADOR]
        usuarios = {
            usuario.email: usuario
            for usuario in get_user_model().objects.filter(email__in=correos)
        }
        if faltan := set(correos) - set(usuarios):
            msg = f"Run seed_demo_usuarios first; missing {', '.join(sorted(faltan))}."
            raise CommandError(msg)
        return usuarios

    def _contrato(self, vencimiento: date, numero: int, responsable: Any) -> Contrato:
        cliente = self._cliente(numero)
        inicio = inicio_para(vencimiento)
        contrato = Contrato.objects.filter(
            cliente=cliente,
            estado=Contrato.Estado.VIGENTE,
        ).first()
        if contrato is None:
            return crear_contrato(
                cliente=cliente,
                marca=Marca.objects.get(nombre="EASY OFFICE"),
                lineas=[
                    LineaContrato(
                        servicio=Servicio.objects.get(codigo="domicilio-tributario"),
                        inmueble=Oficina.objects.get(codigo_sucursal="LF"),
                    ),
                ],
                fecha_inicio=inicio,
                duracion_meses=MESES,
                ejecutivo=responsable,
            )
        contrato.fecha_inicio = inicio
        contrato.fecha_vencimiento = calcular_vencimiento(inicio, MESES)
        contrato.ejecutivo_responsable = responsable
        contrato.save(
            update_fields=[
                "fecha_inicio",
                "fecha_vencimiento",
                "ejecutivo_responsable",
                "updated_at",
            ],
        )
        return contrato

    def _cliente(self, numero: int) -> Cliente:
        empresa, _ = Empresa.objects.get_or_create(
            rut=f"{numero}-{compute_rut_check_digit(str(numero))}",
            defaults={
                "razon_social": f"Comercial Demo Vencimientos {numero} SpA",
                "giro": "Servicios de demostración",
                "email": f"vencimientos{numero}@example.test",
            },
        )
        cliente, _ = Cliente.objects.get_or_create(empresa=empresa)
        return cliente
