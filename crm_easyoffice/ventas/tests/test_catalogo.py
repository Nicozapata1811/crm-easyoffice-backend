"""The service catalogue from Easy Office's contract form (HU-23)."""

from __future__ import annotations

import importlib
from decimal import Decimal
from http import HTTPStatus

import pytest
from django.apps import apps
from django.db import IntegrityError
from django.urls import reverse
from rest_framework.test import APIClient

from crm_easyoffice.clientes.tests.factories import CuentaClienteFactory
from crm_easyoffice.ventas.models import CicloPago
from crm_easyoffice.ventas.models import ItemVenta
from crm_easyoffice.ventas.models import Servicio
from crm_easyoffice.ventas.services import ciclos_pago_activos
from crm_easyoffice.ventas.services import crear_venta
from crm_easyoffice.ventas.tests.factories import ServicioFactory

pytestmark = pytest.mark.django_db

catalogo = importlib.import_module(
    "crm_easyoffice.ventas.migrations.0007_seed_catalogo_formulario",
)

# The form's text, typed again here so a change to the seed is caught.
DOMICILIO = (
    "*Domicilio. Tributario, postal y comercial *Recepción de correspondencia "
    "fiscal *Escaneo de 1 página diaria de correspondencia fiscal no acumulable, "
    "sin costo *Uso 1 hora semanal de estación de trabajo *Inicio de actividades"
)
CREACION = (
    "*Constitución empresa en un día, hasta 3 socios  *Obtención de rut  "
    "*Domicilio tributario x 3 meses  * Inicio de actividad ante el SII  "
    "*Inscripción factura electrónica  * Gestión conjunta solicitud cuenta "
    "emprendedor BancoEstado"
)
WEB_MAIL = "*Servicio web mail corporativo 1 GB + dominio x 1 año"


def servicio(codigo: str) -> Servicio:
    return Servicio.objects.select_related("ciclo_pago_default").get(codigo=codigo)


class TestSeed:
    def test_seed_creates_five_payment_cycles(self):
        assert [ciclo.codigo for ciclo in ciclos_pago_activos()] == [
            "unico",
            "mensual",
            "trimestral",
            "semestral",
            "anual",
        ]
        assert CicloPago.objects.get(codigo="unico").meses is None
        assert CicloPago.objects.get(codigo="anual").meses == 12  # noqa: PLR2004

    @pytest.mark.parametrize(
        ("codigo", "precio", "ciclo", "en_portal"),
        [
            ("domicilio-tributario", Decimal(59990), "anual", True),
            ("creacion-empresas", Decimal(49990), "unico", False),
            ("web-mail-dominio", Decimal(14990), "anual", False),
        ],
    )
    def test_seed_loads_the_four_form_services(self, codigo, precio, ciclo, en_portal):
        cargado = servicio(codigo)

        assert cargado.precio_base == precio
        assert cargado.ciclo_pago_default.codigo == ciclo
        assert cargado.se_vende_en_portal is en_portal
        assert cargado.activo is True
        assert cargado.precio_confirmado is False
        assert cargado.precio_incluye_iva is True

    def test_seed_copies_form_descriptions_verbatim(self):
        assert servicio("domicilio-tributario").descripcion == DOMICILIO
        assert servicio("creacion-empresas").descripcion == CREACION
        assert servicio("web-mail-dominio").descripcion == WEB_MAIL

    def test_seed_leaves_contabilidad_inactive_without_price(self):
        contabilidad = servicio("contabilidad")

        assert contabilidad.precio_base is None
        assert contabilidad.descripcion == ""
        assert contabilidad.ciclo_pago_default is None
        assert contabilidad.activo is False
        assert contabilidad.se_vende_en_portal is False
        assert contabilidad.precio_confirmado is False

    def test_seed_keeps_services_referenced_by_sales(self):
        domicilio = servicio("domicilio-tributario")
        domicilio.precio_base = Decimal(14900)
        domicilio.save()
        venta = crear_venta(CuentaClienteFactory.create().cliente, [(domicilio, 1)])

        catalogo.seed(apps, None)

        assert Servicio.objects.filter(pk=domicilio.pk).exists()
        assert servicio("domicilio-tributario").precio_base == Decimal(59990)
        item = ItemVenta.objects.get(venta=venta)
        assert item.precio_unitario == Decimal(14900)

    def test_seed_does_not_overwrite_confirmed_price(self):
        Servicio.objects.filter(codigo="domicilio-tributario").update(
            precio_base=Decimal(70000),
            precio_confirmado=True,
        )

        catalogo.seed(apps, None)

        assert servicio("domicilio-tributario").precio_base == Decimal(70000)

    def test_seed_leaves_other_services_alone(self):
        firma = servicio("firma-electronica-avanzada")

        catalogo.seed(apps, None)

        assert servicio("firma-electronica-avanzada").precio_base == firma.precio_base

    def test_reverse_removes_only_the_added_services(self):
        catalogo.unseed(apps, None)

        codigos = set(Servicio.objects.values_list("codigo", flat=True))
        assert codigos.isdisjoint(catalogo.NUEVOS)
        assert {"domicilio-tributario", "firma-electronica-avanzada"} <= codigos

    def test_seed_is_idempotent(self):
        catalogo.seed(apps, None)

        assert CicloPago.objects.count() == 5  # noqa: PLR2004
        assert Servicio.objects.filter(codigo="contabilidad").count() == 1


class TestPortal:
    def test_portal_lists_only_services_sold_online(self):
        response = APIClient().get(reverse("portal:servicio-list"))

        codigos = {fila["codigo"] for fila in response.data}
        assert "domicilio-tributario" in codigos
        assert codigos.isdisjoint(
            {"creacion-empresas", "web-mail-dominio", "contabilidad"},
        )
        [domicilio] = [
            f for f in response.data if f["codigo"] == "domicilio-tributario"
        ]
        assert domicilio["ciclo_pago_default"] == "anual"
        assert domicilio["precio_incluye_iva"] is True

    def test_cannot_buy_a_service_not_sold_online(self):
        api_client = APIClient()
        api_client.force_authenticate(CuentaClienteFactory.create().user)

        response = api_client.post(
            reverse("portal:venta-list"),
            {"items": [{"servicio": "creacion-empresas", "cantidad": 1}]},
            format="json",
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_portal_service_requires_price(self):
        with pytest.raises(IntegrityError):
            ServicioFactory.create(precio_base=None, se_vende_en_portal=True)

    def test_service_without_price_may_exist_off_portal(self):
        sin_precio = ServicioFactory.create(precio_base=None, se_vende_en_portal=False)

        assert sin_precio.precio_base is None
