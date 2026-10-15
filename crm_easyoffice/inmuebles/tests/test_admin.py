"""Admin pages for properties. Every value here is synthetic."""

from __future__ import annotations

from http import HTTPStatus

import pytest
from django.urls import reverse

from crm_easyoffice.inmuebles.models import Autorizante
from crm_easyoffice.inmuebles.services import guardar_documento_identidad
from crm_easyoffice.inmuebles.tests.factories import AutorizanteFactory
from crm_easyoffice.inmuebles.tests.factories import OficinaFactory
from crm_easyoffice.inmuebles.tests.factories import archivo

pytestmark = pytest.mark.django_db


def test_change_page_links_to_the_protected_view_not_the_file(admin_client):
    autorizante = AutorizanteFactory.create()
    guardar_documento_identidad(autorizante, archivo())

    response = admin_client.get(
        reverse("admin:inmuebles_autorizante_change", args=[autorizante.pk]),
    )

    assert response.status_code == HTTPStatus.OK
    contenido = response.content.decode()
    assert reverse("inmuebles:documento-identidad", args=[autorizante.pk]) in contenido
    assert autorizante.documento_identidad.name not in contenido


def test_upload_goes_through_the_validators(admin_client):
    autorizante = AutorizanteFactory.create()
    url = reverse("admin:inmuebles_autorizante_change", args=[autorizante.pk])

    response = admin_client.post(
        url,
        {
            "inmueble": autorizante.inmueble_id,
            "persona": autorizante.persona_id,
            "vigente_desde": "2026-01-01",
            "activo": "on",
            "nuevo_documento": archivo("cedula.jpg", b"not an image"),
        },
    )

    assert response.status_code == HTTPStatus.OK  # form redisplayed with errors
    autorizante.refresh_from_db()
    assert not autorizante.documento_identidad


def test_valid_upload_is_stored(admin_client):
    autorizante = AutorizanteFactory.create(inmueble=OficinaFactory.create())
    url = reverse("admin:inmuebles_autorizante_change", args=[autorizante.pk])

    admin_client.post(
        url,
        {
            "inmueble": autorizante.inmueble_id,
            "persona": autorizante.persona_id,
            "vigente_desde": "2026-01-01",
            "activo": "on",
            "nuevo_documento": archivo(),
        },
    )

    assert Autorizante.objects.get(pk=autorizante.pk).documento_identidad
