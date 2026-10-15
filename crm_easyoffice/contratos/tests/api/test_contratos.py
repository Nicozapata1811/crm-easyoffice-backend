"""Contracts API. Every name, RUT and email here is synthetic."""

from __future__ import annotations

import importlib
from http import HTTPStatus

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse
from rest_framework.test import APIClient

from crm_easyoffice.clientes.tests.factories import ClienteFactory
from crm_easyoffice.contratos.models import Contrato
from crm_easyoffice.contratos.tests.factories import marca
from crm_easyoffice.contratos.tests.factories import nuevo_contrato
from crm_easyoffice.contratos.tests.factories import sucursal
from crm_easyoffice.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

seed = importlib.import_module("crm_easyoffice.core.migrations.0002_seed_roles")

LIST_URL = reverse("api:contrato-list")
OPCIONES_URL = reverse("api:contrato-opciones")


def client_for(role: str | None) -> tuple[APIClient, object]:
    user = UserFactory.create()
    if role:
        user.groups.add(Group.objects.get(name=role))
    api_client = APIClient()
    api_client.force_authenticate(user)
    return api_client, user


@pytest.fixture
def ejecutivo():
    return client_for(seed.EJECUTIVO)


def payload(**datos) -> dict:
    return {
        "cliente": ClienteFactory.create().pk,
        "marca": marca().pk,
        "fecha_inicio": "2026-10-02",
        "duracion_meses": 12,
        "email_aviso": "avisos@example.test",
        "movil_aviso": "90000001",
        "servicios": [
            {"servicio": "domicilio-tributario", "inmueble": sucursal("LF").pk},
            {"servicio": "web-mail-dominio"},
        ],
        **datos,
    }


def test_ejecutivo_creates_contract_and_gets_folio(ejecutivo):
    api_client, user = ejecutivo

    response = api_client.post(LIST_URL, payload(), format="json")

    assert response.status_code == HTTPStatus.CREATED, response.data
    assert response.data["folio"].startswith("LF-0001-")
    assert response.data["fecha_vencimiento"] == "2027-10-01"
    assert [s["servicio"] for s in response.data["servicios"]] == [
        "domicilio-tributario",
        "web-mail-dominio",
    ]
    assert response.data["servicios"][0]["precio"] == "59990"
    contrato = Contrato.objects.get(pk=response.data["id"])
    assert contrato.ejecutivo_responsable == user
    assert contrato.cuenta_pago == marca().cuenta_pago_default


def test_invalid_contract_reports_the_field(ejecutivo):
    api_client, _ = ejecutivo

    response = api_client.post(
        LIST_URL,
        payload(servicios=[{"servicio": "creacion-empresas"}]),
        format="json",
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "codigo_sucursal" in response.data


def test_contracts_cannot_be_deleted_or_edited(admin_user):
    # Even a superuser, who holds every permission, finds no such method.
    contrato = nuevo_contrato()
    api_client = APIClient()
    api_client.force_authenticate(admin_user)
    url = reverse("api:contrato-detail", args=[contrato.pk])

    assert api_client.delete(url).status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert api_client.patch(url, {}).status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert Contrato.objects.filter(pk=contrato.pk).exists()


def test_search_contract_by_folio(ejecutivo):
    api_client, _ = ejecutivo
    buscado = nuevo_contrato()
    nuevo_contrato()

    response = api_client.get(LIST_URL, {"buscar": buscado.folio.lower()})

    assert [fila["id"] for fila in response.data["results"]] == [buscado.pk]


def test_search_contract_by_client(ejecutivo):
    api_client, _ = ejecutivo
    buscado = nuevo_contrato()
    nuevo_contrato()

    response = api_client.get(LIST_URL, {"buscar": buscado.cliente.parte.rut})

    assert [fila["id"] for fila in response.data["results"]] == [buscado.pk]


def test_list_filters_by_branch_brand_and_year(ejecutivo):
    api_client, _ = ejecutivo
    nuevo_contrato()
    inoffice = nuevo_contrato(marca=marca("INOFFICE"))

    por_marca = api_client.get(LIST_URL, {"marca": marca("INOFFICE").pk})
    por_sucursal = api_client.get(LIST_URL, {"sucursal": "vl"})
    por_anio = api_client.get(LIST_URL, {"anio": 2026})

    assert [f["id"] for f in por_marca.data["results"]] == [inoffice.pk]
    assert por_sucursal.data["results"] == []
    assert len(por_anio.data["results"]) == 2  # noqa: PLR2004


def test_opciones_lists_catalogues(ejecutivo):
    api_client, _ = ejecutivo

    response = api_client.get(OPCIONES_URL)

    assert response.status_code == HTTPStatus.OK
    assert response.data["duraciones"] == [1, 3, 4, 6, 12]
    assert {m["nombre"] for m in response.data["marcas"]} == {"EASY OFFICE", "INOFFICE"}


def test_opciones_requires_permission_to_create():
    api_client, _ = client_for(None)

    assert api_client.get(OPCIONES_URL).status_code == HTTPStatus.FORBIDDEN


def test_anonymous_cannot_list_contracts():
    assert APIClient().get(LIST_URL).status_code == HTTPStatus.FORBIDDEN


def test_ejecutivo_never_deletes_contracts():
    _, user = client_for(seed.EJECUTIVO)

    assert user.has_perm("contratos.add_contrato")
    assert user.has_perm("contratos.view_contrato")
    assert not user.has_perm("contratos.delete_contrato")
    assert not user.has_perm("contratos.view_correlativofolio")
