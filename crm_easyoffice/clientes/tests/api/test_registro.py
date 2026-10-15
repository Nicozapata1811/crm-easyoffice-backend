"""Portal registration API tests. All data here is synthetic."""

from __future__ import annotations

from http import HTTPStatus

import pytest
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient

from crm_easyoffice.clientes.tests.factories import CuentaClienteFactory
from crm_easyoffice.clientes.tests.factories import PersonaFactory
from crm_easyoffice.clientes.tests.factories import synthetic_rut

PASSWORD = "synthetic-Pass-123"  # noqa: S105
REGISTRO_URL = reverse("portal:registro")

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _reset_throttle():
    cache.clear()


def payload(**overrides) -> dict:
    return {
        "tipo": "persona",
        "rut": "41.000.010-" + synthetic_rut(41_000_010)[-1],
        "nombres": "Matías",
        "apellido_paterno": "Rojas",
        "email": "matias.rojas@example.test",
        "password": PASSWORD,
        **overrides,
    }


def test_registration_starts_a_client_session():
    api_client = APIClient()

    response = api_client.post(REGISTRO_URL, payload(), format="json")

    assert response.status_code == HTTPStatus.CREATED
    assert response.data["tipo"] == "cliente"
    assert response.data["cliente"]["codigo"].startswith("CLI-")
    assert response.data["permisos"] == []
    me = api_client.get(reverse("auth:me"))
    assert me.data["cliente"]["id"] == response.data["cliente"]["id"]


def test_me_keeps_deprecated_folio_alias():
    api_client = APIClient()
    api_client.post(REGISTRO_URL, payload(), format="json")

    cliente = api_client.get(reverse("auth:me")).data["cliente"]

    assert cliente["folio"] == cliente["codigo"]


def test_registration_requires_csrf():
    api_client = APIClient(enforce_csrf_checks=True)

    response = api_client.post(REGISTRO_URL, payload(), format="json")

    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.parametrize(
    ("overrides", "campo"),
    [
        ({"nombres": ""}, "nombres"),
        ({"tipo": "empresa"}, "razon_social"),
        ({"rut": "12345678-9"}, "rut"),
        ({"password": "123"}, "password"),
    ],
)
def test_invalid_data_is_reported_by_field(overrides, campo):
    response = APIClient().post(REGISTRO_URL, payload(**overrides), format="json")

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert campo in response.data


def test_rejections_share_one_generic_answer():
    existente = PersonaFactory.create()
    con_cuenta = CuentaClienteFactory.create().cliente.persona

    otro_email = APIClient().post(
        REGISTRO_URL,
        payload(rut=existente.rut, email="intruso@example.test"),
        format="json",
    )
    ya_registrado = APIClient().post(
        REGISTRO_URL,
        payload(rut=con_cuenta.rut, email=con_cuenta.email),
        format="json",
    )

    assert otro_email.status_code == HTTPStatus.BAD_REQUEST
    assert otro_email.data == ya_registrado.data
    assert set(otro_email.data) == {"detail"}


def test_client_user_cannot_reach_staff_endpoints():
    api_client = APIClient()
    api_client.force_authenticate(CuentaClienteFactory.create().user)

    assert (
        api_client.get(reverse("api:cliente-list")).status_code == HTTPStatus.FORBIDDEN
    )
    assert (
        api_client.get(reverse("panel:indicadores")).status_code == HTTPStatus.FORBIDDEN
    )


def test_staff_session_reports_staff_type(user):
    api_client = APIClient()
    api_client.force_authenticate(user)

    response = api_client.get(reverse("auth:me"))

    assert response.data["tipo"] == "staff"
    assert response.data["cliente"] is None
