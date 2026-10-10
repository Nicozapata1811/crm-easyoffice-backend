"""Portal sales API. Every name, RUT and email here is synthetic."""

from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from crm_easyoffice.clientes.tests.factories import CuentaClienteFactory
from crm_easyoffice.ventas.models import OrdenPago
from crm_easyoffice.ventas.models import Venta
from crm_easyoffice.ventas.tests.factories import OrdenPagoFactory
from crm_easyoffice.ventas.tests.factories import ServicioFactory
from crm_easyoffice.ventas.tests.factories import VentaFactory

pytestmark = pytest.mark.django_db

VENTAS_URL = reverse("portal:venta-list")


def pagar_url(venta: Venta) -> str:
    return reverse("portal:venta-pagar", args=[venta.pk])


def orden_url(orden: OrdenPago) -> str:
    return reverse("portal:orden-detail", args=[orden.pk])


@pytest.fixture
def cuenta():
    return CuentaClienteFactory.create()


@pytest.fixture
def cliente_api(cuenta) -> APIClient:
    api_client = APIClient()
    api_client.force_authenticate(cuenta.user)
    return api_client


@pytest.fixture
def tareas(monkeypatch):
    enviadas: dict[str, list[int]] = {"crear": [], "sincronizar": []}
    monkeypatch.setattr(
        "crm_easyoffice.ventas.tasks.crear_orden_en_proveedor.delay",
        enviadas["crear"].append,
    )
    monkeypatch.setattr(
        "crm_easyoffice.ventas.api.views.sincronizar_orden.delay",
        enviadas["sincronizar"].append,
    )
    return enviadas


def test_catalogue_is_public_and_flags_unconfirmed_prices():
    ServicioFactory.create(codigo="domicilio-prueba")
    ServicioFactory.create(activo=False)

    response = APIClient().get(reverse("portal:servicio-list"))

    assert response.status_code == HTTPStatus.OK
    codigos = {servicio["codigo"] for servicio in response.data}
    assert "domicilio-prueba" in codigos
    assert all(servicio["precio_confirmado"] is False for servicio in response.data)


def test_client_buys_at_the_list_price(cliente_api, cuenta):
    servicio = ServicioFactory.create()

    response = cliente_api.post(
        VENTAS_URL,
        {"items": [{"servicio": servicio.codigo, "cantidad": 1}], "total": 1},
        format="json",
    )

    assert response.status_code == HTTPStatus.CREATED
    venta = Venta.objects.get(pk=response.data["id"])
    assert venta.cliente == cuenta.cliente
    assert venta.total == servicio.precio_base


def test_paying_returns_the_attempt(
    cliente_api,
    cuenta,
    tareas,
    django_capture_on_commit_callbacks,
):
    venta = VentaFactory.create(cliente=cuenta.cliente)

    with django_capture_on_commit_callbacks(execute=True):
        response = cliente_api.post(pagar_url(venta))

    assert response.status_code == HTTPStatus.ACCEPTED
    assert response.data["estado"] == OrdenPago.Estado.CREANDO
    assert tareas["crear"] == [response.data["id"]]


def test_a_paid_sale_answers_conflict(cliente_api, cuenta, tareas):
    venta = VentaFactory.create(cliente=cuenta.cliente, estado=Venta.Estado.PAGADA)

    assert cliente_api.post(pagar_url(venta)).status_code == HTTPStatus.CONFLICT


def test_a_stale_pending_order_is_checked_again(
    cliente_api,
    cuenta,
    tareas,
    django_capture_on_commit_callbacks,
):
    orden = OrdenPagoFactory.create(venta__cliente=cuenta.cliente)
    OrdenPago.objects.filter(pk=orden.pk).update(
        updated_at=timezone.now() - timedelta(minutes=1),
    )

    with django_capture_on_commit_callbacks(execute=True):
        response = cliente_api.get(orden_url(orden))

    assert response.data["id_externo"] == orden.id_externo
    assert tareas["sincronizar"] == [orden.pk]


def test_another_clients_records_are_not_found(cliente_api, tareas):
    ajena = OrdenPagoFactory.create()

    assert cliente_api.get(orden_url(ajena)).status_code == HTTPStatus.NOT_FOUND
    assert cliente_api.post(pagar_url(ajena.venta)).status_code == HTTPStatus.NOT_FOUND
    assert cliente_api.get(VENTAS_URL).data["count"] == 0


@pytest.mark.parametrize("quien", ["anonimo", "staff"])
def test_only_clients_reach_the_portal_sales(quien, user):
    api_client = APIClient()
    if quien == "staff":
        api_client.force_authenticate(user)

    assert api_client.get(VENTAS_URL).status_code == HTTPStatus.FORBIDDEN
