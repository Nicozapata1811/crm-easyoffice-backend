"""Admin pages for parties. Every value here is synthetic."""

from __future__ import annotations

from http import HTTPStatus

import pytest
from django.urls import reverse

from crm_easyoffice.clientes.tests.factories import EmpresaFactory
from crm_easyoffice.clientes.tests.factories import PersonaFactory

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("modelo", "factory", "campo"),
    [("persona", PersonaFactory, "rut"), ("empresa", EmpresaFactory, "razon_social")],
)
def test_changelist_searches(admin_client, modelo, factory, campo):
    buscado = factory.create()
    factory.create()

    response = admin_client.get(
        reverse(f"admin:clientes_{modelo}_changelist"),
        {"q": getattr(buscado, campo)},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.context["cl"].result_count == 1


def test_parties_cannot_be_deleted_from_the_admin(admin_client):
    persona = PersonaFactory.create()

    response = admin_client.get(
        reverse("admin:clientes_persona_delete", args=[persona.pk]),
    )

    assert response.status_code == HTTPStatus.FORBIDDEN
