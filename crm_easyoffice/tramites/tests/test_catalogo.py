from http import HTTPStatus

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from crm_easyoffice.tramites.catalogo import buscar_plan
from crm_easyoffice.tramites.catalogo import buscar_servicio


def test_buscar_servicio_and_plan():
    assert buscar_servicio("domicilio-tributario") is not None
    assert buscar_servicio("no-existe") is None
    assert buscar_plan("domicilio-tributario", "anual") is not None
    assert buscar_plan("domicilio-tributario", "trimestral") is None
    assert buscar_plan("no-existe", "anual") is None


@pytest.mark.django_db
def test_catalogue_endpoint_returns_seeded_plans_to_anonymous_users(settings):
    settings.PORTAL_BASE_URL = "https://portal.example.test/"

    response = APIClient().get(reverse("api:catalogo"))

    assert response.status_code == HTTPStatus.OK
    [servicio] = response.json()["servicios"]
    assert servicio["slug"] == "domicilio-tributario"
    assert servicio["planes"] == [
        {
            "slug": "anual",
            "nombre": "Anual",
            "meses": 12,
            "precio": 59990,
            "moneda": "CLP",
            "precio_confirmado": False,
            "enlace": "https://portal.example.test/domicilio-tributario?plan=anual&origen=sitio",
        },
        {
            "slug": "semestral",
            "nombre": "Semestral",
            "meses": 6,
            "precio": 39990,
            "moneda": "CLP",
            "precio_confirmado": False,
            "enlace": "https://portal.example.test/domicilio-tributario?plan=semestral&origen=sitio",
        },
    ]
