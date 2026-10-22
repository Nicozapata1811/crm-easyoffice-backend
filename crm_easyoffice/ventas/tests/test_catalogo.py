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
from crm_easyoffice.contratos.services import LineaContrato
from crm_easyoffice.contratos.tests.factories import domicilio_en
from crm_easyoffice.contratos.tests.factories import nuevo_contrato
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
    def test_portal_lists_only_visible_or_bookable_services(self):
        response = APIClient().get(reverse("portal:servicio-list"))

        codigos = {fila["codigo"] for fila in response.data}
        assert {"domicilio-tributario", "firma-electronica-avanzada"} <= codigos
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


visibles = importlib.import_module(
    "crm_easyoffice.ventas.migrations.0010_seed_servicios_visibles",
)
planes_bodega = importlib.import_module(
    "crm_easyoffice.ventas.migrations.0013_seed_planes_bodega",
)

# The bodega left this list when it became bookable by plan (0013).
PROXIMAMENTE = [
    "arriendo-vehiculo",
    "arriendo-estacionamiento",
    "acuerdo-accionistas",
    "poder-simple",
]


class TestSeedVisibles:
    @pytest.mark.parametrize("codigo", PROXIMAMENTE)
    def test_seed_adds_visible_services_not_sold_online(self, codigo):
        cargado = servicio(codigo)

        assert cargado.visible_en_portal is True
        assert cargado.se_vende_en_portal is False
        assert cargado.activo is True
        assert cargado.precio_base is None
        assert cargado.precio_confirmado is False
        assert cargado.ciclo_pago_default is None
        assert cargado.descripcion

    def test_seed_shows_domicilio_first(self):
        domicilio = servicio("domicilio-tributario")

        assert domicilio.visible_en_portal is True
        assert domicilio.se_vende_en_portal is True
        assert domicilio.orden < min(servicio(c).orden for c in PROXIMAMENTE)

    def test_signature_add_on_stays_hidden_but_bookable(self):
        firma = servicio("firma-electronica-avanzada")

        assert firma.visible_en_portal is False
        assert firma.se_vende_en_portal is True

    def test_seed_is_idempotent_and_keeps_admin_edits(self):
        Servicio.objects.filter(codigo="poder-simple").update(
            descripcion="Texto editado",
        )

        visibles.seed(apps, None)

        assert Servicio.objects.filter(codigo__in=PROXIMAMENTE).count() == len(
            PROXIMAMENTE,
        )
        assert servicio("poder-simple").descripcion == "Texto editado"

    def test_seed_leaves_existing_sales_untouched(self):
        domicilio = servicio("domicilio-tributario")
        venta = crear_venta(CuentaClienteFactory.create().cliente, [(domicilio, 1)])

        visibles.seed(apps, None)

        assert servicio("domicilio-tributario").precio_base == domicilio.precio_base
        item = ItemVenta.objects.get(venta=venta)
        assert item.precio_unitario == domicilio.precio_base

    def test_reverse_keeps_services_with_a_contract(self):
        nuevo_contrato(
            lineas=[
                domicilio_en("LF"),
                LineaContrato(
                    servicio=servicio("poder-simple"),
                    ciclo_pago=CicloPago.objects.get(codigo="mensual"),
                    precio=Decimal(50000),
                ),
            ],
        )

        # Migrations reverse in order: the bodega's plans go first.
        planes_bodega.unseed(apps, None)
        visibles.unseed(apps, None)

        codigos = set(Servicio.objects.values_list("codigo", flat=True))
        assert "poder-simple" in codigos
        assert codigos.isdisjoint({*PROXIMAMENTE, "bodega"} - {"poder-simple"})
        assert servicio("domicilio-tributario").visible_en_portal is False


class TestVisibilidad:
    def test_visible_service_without_price_may_exist_off_sale(self):
        sin_precio = ServicioFactory.create(
            precio_base=None,
            se_vende_en_portal=False,
            visible_en_portal=True,
        )

        assert sin_precio.precio_base is None

    def test_bookable_service_requires_price_even_when_visible(self):
        with pytest.raises(IntegrityError):
            ServicioFactory.create(
                precio_base=None,
                se_vende_en_portal=True,
                visible_en_portal=True,
            )

    def test_hidden_bookable_service_is_allowed(self):
        complemento = ServicioFactory.create(visible_en_portal=False)

        assert complemento.se_vende_en_portal is True

    def test_payload_says_whether_each_service_is_visible_and_bookable(self):
        response = APIClient().get(reverse("portal:servicio-list"))

        por_codigo = {fila["codigo"]: fila for fila in response.data}
        assert por_codigo["arriendo-vehiculo"]["visible_en_portal"] is True
        assert por_codigo["arriendo-vehiculo"]["se_vende_en_portal"] is False
        assert por_codigo["arriendo-vehiculo"]["precio_base"] is None
        assert por_codigo["bodega"]["se_vende_en_portal"] is True
        assert por_codigo["domicilio-tributario"]["se_vende_en_portal"] is True
        assert por_codigo["firma-electronica-avanzada"]["visible_en_portal"] is False

    def test_payload_excludes_inactive_and_internal_services(self):
        ServicioFactory.create(codigo="inactivo", visible_en_portal=True, activo=False)
        ServicioFactory.create(
            codigo="interno",
            se_vende_en_portal=False,
            visible_en_portal=False,
        )

        response = APIClient().get(reverse("portal:servicio-list"))

        codigos = {fila["codigo"] for fila in response.data}
        assert codigos.isdisjoint({"inactivo", "interno"})

    def test_payload_follows_the_admin_order(self):
        Servicio.objects.filter(codigo="poder-simple").update(orden=1)

        response = APIClient().get(reverse("portal:servicio-list"))

        visibles_en_orden = [
            fila["codigo"] for fila in response.data if fila["visible_en_portal"]
        ]
        assert visibles_en_orden == [
            "poder-simple",
            "domicilio-tributario",
            "bodega",
            "arriendo-vehiculo",
            "arriendo-estacionamiento",
            "acuerdo-accionistas",
        ]

    def test_cannot_buy_a_visible_service_not_sold_online(self):
        api_client = APIClient()
        api_client.force_authenticate(CuentaClienteFactory.create().user)

        response = api_client.post(
            reverse("portal:venta-list"),
            {"items": [{"servicio": "poder-simple", "cantidad": 1}]},
            format="json",
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_can_buy_a_hidden_add_on_sold_online(self):
        api_client = APIClient()
        api_client.force_authenticate(CuentaClienteFactory.create().user)

        response = api_client.post(
            reverse("portal:venta-list"),
            {"items": [{"servicio": "firma-electronica-avanzada", "cantidad": 1}]},
            format="json",
        )

        assert response.status_code == HTTPStatus.CREATED
