"""Protected identity-card download. Every value here is synthetic."""

from __future__ import annotations

import importlib
from http import HTTPStatus

import pytest
from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.urls import reverse
from rest_framework.test import APIClient

from crm_easyoffice.core.models import RegistroAuditoria
from crm_easyoffice.inmuebles.services import guardar_documento_identidad
from crm_easyoffice.inmuebles.tests.factories import JPEG
from crm_easyoffice.inmuebles.tests.factories import AutorizanteFactory
from crm_easyoffice.inmuebles.tests.factories import archivo
from crm_easyoffice.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

seed = importlib.import_module("crm_easyoffice.core.migrations.0002_seed_roles")


def url(autorizante) -> str:
    return reverse("inmuebles:documento-identidad", args=[autorizante.pk])


def client_for(role: str | None) -> APIClient:
    user = UserFactory.create()
    if role:
        user.groups.add(Group.objects.get(name=role))
    api_client = APIClient()
    api_client.force_authenticate(user)
    return api_client


@pytest.fixture
def autorizante():
    autorizante = AutorizanteFactory.create()
    guardar_documento_identidad(autorizante, archivo())
    return autorizante


def test_administrador_downloads_identity_card(autorizante):
    response = client_for(seed.ADMINISTRADOR).get(url(autorizante))

    assert response.status_code == HTTPStatus.OK
    assert b"".join(response.streaming_content) == JPEG
    assert response["Content-Type"] == "image/jpeg"


def test_identity_card_response_is_attachment_no_store(autorizante):
    response = client_for(seed.ADMINISTRADOR).get(url(autorizante))

    assert response["Content-Disposition"].startswith("attachment;")
    assert "no-store" in response["Cache-Control"]
    assert response["X-Content-Type-Options"] == "nosniff"


def test_ejecutivo_cannot_download_identity_card(autorizante):
    response = client_for(seed.EJECUTIVO).get(url(autorizante))

    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.parametrize("role", [None, "anonymous"])
def test_identity_card_view_requires_permission(autorizante, role):
    api_client = APIClient() if role == "anonymous" else client_for(role)

    response = api_client.get(url(autorizante))

    assert response.status_code == HTTPStatus.FORBIDDEN


def test_missing_identity_card_is_not_found():
    sin_cedula = AutorizanteFactory.create()

    response = client_for(seed.ADMINISTRADOR).get(url(sin_cedula))

    assert response.status_code == HTTPStatus.NOT_FOUND


def test_ejecutivo_can_view_authorisers_but_not_their_card():
    ejecutivo = UserFactory.create()
    ejecutivo.groups.add(Group.objects.get(name=seed.EJECUTIVO))

    assert ejecutivo.has_perm("inmuebles.view_autorizante")
    assert not ejecutivo.has_perm("inmuebles.change_autorizante")
    assert not ejecutivo.has_perm("inmuebles.descargar_documento_identidad")


def test_card_permission_is_outside_the_ejecutivo_seed_filter():
    # core's seed_roles grants Ejecutivo every inmuebles "view_*" permission and
    # later migrations re-run it, so the card permission must not match.
    concedidas = Permission.objects.filter(
        content_type__app_label="inmuebles",
        codename__startswith="view_",
    )

    assert not concedidas.filter(codename="descargar_documento_identidad").exists()


def test_each_access_to_the_identity_card_is_audited(autorizante):
    guardar_documento_identidad(autorizante, archivo(), reverso=True)
    administrador = client_for(seed.ADMINISTRADOR)

    reverso = administrador.get(url(autorizante), {"lado": "reverso"})
    anverso = administrador.get(url(autorizante))

    assert reverso.status_code == anverso.status_code == HTTPStatus.OK
    accesos = RegistroAuditoria.objects.filter(
        accion=RegistroAuditoria.Accion.ACCESO_DOCUMENTO_IDENTIDAD,
        entidad="inmuebles.autorizante",
        registro_id=autorizante.pk,
    ).order_by("pk")
    assert [a.valor_nuevo for a in accesos] == [
        {"lado": "reverso"},
        {"lado": "anverso"},
    ]
    assert all(a.usuario_id and a.origen == "api" for a in accesos)


def test_a_denied_access_is_not_audited_as_an_access(autorizante):
    client_for(seed.EJECUTIVO).get(url(autorizante))

    assert not RegistroAuditoria.objects.filter(
        accion=RegistroAuditoria.Accion.ACCESO_DOCUMENTO_IDENTIDAD,
    ).exists()
