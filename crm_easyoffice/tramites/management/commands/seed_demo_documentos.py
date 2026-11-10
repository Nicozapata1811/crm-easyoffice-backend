"""One demo case per document implemented directly (PLT-03 …). Fictitious data.

For local development and staging demos only. The client is the first demo
portal company (``seed_demo_usuarios``), so the sale can be paid in the
portal; the parties' RUTs are in the test PSC's fictitious registry
(firma_sandbox/fixtures/identidades_demo.json), so the advanced signature
works too. Running it again adds nothing.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.utils import timezone

from crm_easyoffice.clientes.models import Cliente
from crm_easyoffice.clientes.services import datos_contratante
from crm_easyoffice.core.validators import compute_rut_check_digit
from crm_easyoffice.tramites.formularios import formulario_de
from crm_easyoffice.tramites.models import Tramite
from crm_easyoffice.tramites.services import iniciar_tramite
from crm_easyoffice.tramites.services import tipo_tramite

# The first demo portal client of seed_demo_usuarios.
NUMERO_CLIENTE = "76950001"
RUT_CLIENTE = f"{NUMERO_CLIENTE}-{compute_rut_check_digit(NUMERO_CLIENTE)}"
EJECUTIVO = "ejecutivo@example.test"

# Fictitious people the test PSC knows by these names.
REPRESENTANTE = {
    "rut": "90000302-1",
    "nombres": "Representante",
    "apellido_paterno": "Demo",
    "apellido_materno": "2",
    "domicilio": "Avenida Ficticia 100",
    "comuna": "Santiago",
    "region": "Región Metropolitana de Santiago",
    "email": "representante.demo2@example.test",
}
ARRENDADOR = {
    "rut": "90000303-K",
    "nombres": "Representante",
    "apellido_paterno": "Demo",
    "apellido_materno": "3",
    "domicilio": "Pasaje Inventado 200",
    "comuna": "Ñuñoa",
    "email": "representante.demo3@example.test",
}


def _seccion_a(cliente: Cliente) -> dict[str, Any]:
    """The client's own records, or the demo representative when it has none."""
    datos = datos_contratante(cliente)
    datos["empresa"]["giro"] = datos["empresa"]["giro"] or "Servicios de demostración"
    if not datos["representante"]["rut"]:
        datos["representante"] = dict(REPRESENTANTE)
        datos["personeria"] = {
            "fecha_instrumento": "2025-03-10",
            "sitio_o_notaria": "www.tuempresaenundia.cl",
        }
    return datos


def arriendo_vehiculo(cliente: Cliente) -> dict[str, Any]:
    """A vehicle lease (PLT-03) as its form posts it."""
    hoy = timezone.localdate()
    return {
        **_seccion_a(cliente),
        "arrendador": dict(ARRENDADOR),
        "domicilio_empresa": "Avenida Ficticia 100, oficina 5",
        "comuna": "Santiago",
        "fecha": hoy.isoformat(),
        "vehiculo": {
            "marca": "Marca Demo",
            "modelo": "Furgón D1",
            "anio": 2022,
            "patente": "ZZZZ99",
            "color": "Blanco",
            "vin": "DEMO0000000000001",
        },
        "plazo_meses": 12,
        "fecha_inicio": date(hoy.year, hoy.month, 1).isoformat(),
        "renta": 180000,
        "dia_pago": 5,
        "medio_pago": "transferencia",
    }


# Case type code → the demo request of its form. A new document adds its own.
DEMOS = {"arriendo-vehiculo": arriendo_vehiculo}


class Command(BaseCommand):
    help = "Start one demo case per directly implemented document. DEBUG only."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--force",
            action="store_true",
            help="Run even when DEBUG is off (staging).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG and not options["force"]:
            msg = "Refusing to load demo data with DEBUG off; pass --force."
            raise CommandError(msg)
        if "production" in (settings.SETTINGS_MODULE or ""):
            msg = "Refusing to load demo data with production settings."
            raise CommandError(msg)

        cliente = Cliente.objects.filter(empresa__rut=RUT_CLIENTE).first()
        if cliente is None:
            msg = "Run seed_demo_usuarios first: the demo client does not exist."
            raise CommandError(msg)
        ejecutivo = get_user_model().objects.filter(email=EJECUTIVO).first()

        for codigo, demo in DEMOS.items():
            tipo = tipo_tramite(codigo)
            if Tramite.objects.filter(cliente=cliente, tipo=tipo).exists():
                self.stdout.write(f"{tipo.nombre}: the demo case already exists.")
                continue
            serializer = formulario_de(tipo).Serializer(data=demo(cliente))
            serializer.is_valid(raise_exception=True)
            tramite = iniciar_tramite(
                tipo,
                cliente,
                dict(serializer.validated_data),
                canal=Tramite.Canal.BACKOFFICE,
                usuario=ejecutivo,
            )
            self.stdout.write(self.style.SUCCESS(f"{tipo.nombre}: {tramite.folio}."))
