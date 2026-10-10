"""Backoffice sales API. All data here is synthetic."""

from __future__ import annotations

import importlib
from http import HTTPStatus

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse
from rest_framework.test import APIClient

from crm_easyoffice.users.tests.factories import UserFactory
from crm_easyoffice.ventas.tests.factories import OrdenPagoFactory
from crm_easyoffice.ventas.tests.factories import VentaFactory

seed = importlib.import_module("crm_easyoffice.core.migrations.0002_seed_roles")

LIST_URL = reverse("api:venta-list")

pytestmark = pytest.mark.django_db


def client_for(role: str | None) -> APIClient:
    user = UserFactory.create()
    if role:
        user.groups.add(Group.objects.get(name=role))
    api_client = APIClient()
    api_client.force_authenticate(user)
    return api_client


@pytest.mark.parametrize(
    ("role", "esperado"),
    [
        (seed.ADMINISTRADOR, HTTPStatus.OK),
        (seed.EJECUTIVO, HTTPStatus.OK),
        (None, HTTPStatus.FORBIDDEN),
    ],
)
def test_reading_sales_needs_the_view_permission(role, esperado):
    assert client_for(role).get(LIST_URL).status_code == esperado


def test_detail_carries_orders_and_payments():
    orden = OrdenPagoFactory.create()

    response = client_for(seed.EJECUTIVO).get(
        reverse("api:venta-detail", args=[orden.venta_id]),
    )

    assert response.data["cliente"]["folio"] == orden.venta.cliente.folio
    assert response.data["ordenes"][0]["id_externo"] == orden.id_externo
    assert response.data["ordenes"][0]["pagos"] == []


def test_search_by_sale_folio_or_client():
    buscada = VentaFactory.create()
    VentaFactory.create()
    api_client = client_for(seed.ADMINISTRADOR)

    por_folio = api_client.get(LIST_URL, {"buscar": buscada.folio})
    por_rut = api_client.get(LIST_URL, {"buscar": buscada.cliente.persona.rut})

    assert [venta["id"] for venta in por_folio.data["results"]] == [buscada.pk]
    assert [venta["id"] for venta in por_rut.data["results"]] == [buscada.pk]


def test_sales_are_read_only():
    venta = VentaFactory.create()
    api_client = client_for(seed.ADMINISTRADOR)
    detalle = reverse("api:venta-detail", args=[venta.pk])

    assert api_client.post(LIST_URL, {}).status_code == HTTPStatus.FORBIDDEN
    assert api_client.patch(detalle, {}).status_code == HTTPStatus.FORBIDDEN
    assert api_client.delete(detalle).status_code == HTTPStatus.FORBIDDEN
