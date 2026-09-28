from datetime import UTC
from datetime import datetime
from http import HTTPStatus

import pytest
from django.urls import reverse

from crm_easyoffice.prospectos.models import Prospecto


@pytest.fixture
def prospecto(db) -> Prospecto:
    return Prospecto.objects.create(
        formato="generico",
        origen="sitio",
        nombre="Carla Demo",
        email="carla@example.com",
        recibido_en=datetime(2026, 9, 27, 15, 0, tzinfo=UTC),
        payload_original={"nombre": "Carla Demo"},
        dedup_key="a" * 64,
    )


class TestProspectoAdmin:
    def test_changelist(self, admin_client, prospecto):
        response = admin_client.get(reverse("admin:prospectos_prospecto_changelist"))
        assert response.status_code == HTTPStatus.OK

    def test_add_is_disabled(self, admin_client):
        response = admin_client.get(reverse("admin:prospectos_prospecto_add"))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_webhook_fields_are_read_only(self, admin_client, prospecto):
        url = reverse("admin:prospectos_prospecto_change", args=[prospecto.pk])

        response = admin_client.post(
            url,
            {
                "estado": Prospecto.Estado.CONTACTADO,
                "nombre": "Otro Nombre",
                "cliente": "",
            },
        )

        assert response.status_code == HTTPStatus.FOUND
        prospecto.refresh_from_db()
        assert prospecto.estado == Prospecto.Estado.CONTACTADO
        assert prospecto.nombre == "Carla Demo"
