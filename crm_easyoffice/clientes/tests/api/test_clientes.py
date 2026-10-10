"""Client API tests. Every name, RUT and contact detail here is synthetic."""

from __future__ import annotations

import importlib
from datetime import date
from http import HTTPStatus

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse
from rest_framework.test import APIClient

from crm_easyoffice.clientes.models import Cliente
from crm_easyoffice.clientes.models import Persona
from crm_easyoffice.clientes.models import RepresentanteLegal
from crm_easyoffice.clientes.tests.factories import ClienteFactory
from crm_easyoffice.clientes.tests.factories import EmpresaFactory
from crm_easyoffice.clientes.tests.factories import PersonaFactory
from crm_easyoffice.users.tests.factories import UserFactory

seed = importlib.import_module("crm_easyoffice.core.migrations.0002_seed_roles")

LIST_URL = reverse("api:cliente-list")


def detail_url(cliente: Cliente) -> str:
    return reverse("api:cliente-detail", args=[cliente.pk])


def client_for(role: str | None) -> APIClient:
    user = UserFactory.create()
    if role:
        user.groups.add(Group.objects.get(name=role))
    api_client = APIClient()
    api_client.force_authenticate(user)
    return api_client


@pytest.fixture
def administrador(db) -> APIClient:
    return client_for(seed.ADMINISTRADOR)


@pytest.fixture
def ejecutivo(db) -> APIClient:
    return client_for(seed.EJECUTIVO)


def persona_payload(**overrides: str) -> dict:
    persona = {
        "rut": "11.111.112-k",
        "nombres": "Persona",
        "apellido_paterno": "De Ejemplo",
        "apellido_materno": "",
        "email": "persona@example.test",
        "telefono": "+56 9 0000 0001",
    }
    return {"tipo": "persona", "persona": {**persona, **overrides}}


def empresa_payload(**overrides: str) -> dict:
    empresa = {
        "rut": "76.543.210-3",
        "razon_social": "Empresa de Ejemplo SpA",
        "nombre_fantasia": "Ejemplo",
        "giro": "Asesorías",
        "email": "empresa@example.test",
        "telefono": "",
    }
    return {"tipo": "empresa", "empresa": {**empresa, **overrides}}


class TestCreate:
    def test_creates_a_persona_with_a_normalised_rut_and_a_folio(self, ejecutivo):
        response = ejecutivo.post(LIST_URL, persona_payload(), format="json")

        assert response.status_code == HTTPStatus.CREATED
        cliente = Cliente.objects.get(pk=response.data["id"])
        assert cliente.parte.rut == "11111112-K"
        assert cliente.folio == f"CLI-{cliente.pk:06d}"
        assert response.data["folio"] == cliente.folio
        assert response.data["tipo"] == "persona"
        assert response.data["empresa"] is None

    def test_creates_an_empresa(self, ejecutivo):
        response = ejecutivo.post(LIST_URL, empresa_payload(), format="json")

        assert response.status_code == HTTPStatus.CREATED
        assert response.data["tipo"] == "empresa"
        assert response.data["empresa"]["rut"] == "76543210-3"
        assert response.data["representantes"] == []

    def test_rejects_an_invalid_check_digit(self, ejecutivo):
        response = ejecutivo.post(
            LIST_URL,
            persona_payload(rut="11111112-1"),
            format="json",
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "rut" in response.data["persona"]

    def test_rejects_a_rut_that_is_already_a_client(self, ejecutivo):
        ejecutivo.post(LIST_URL, persona_payload(), format="json")

        response = ejecutivo.post(
            LIST_URL,
            persona_payload(rut="11111112-K", nombres="Otra"),
            format="json",
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "rut" in response.data["persona"]
        assert Cliente.objects.count() == 1

    def test_links_a_legal_representative_who_becomes_a_client(self, ejecutivo):
        representante = PersonaFactory.create(rut="11111112-K")
        RepresentanteLegal.objects.create(
            persona=representante,
            empresa=EmpresaFactory.create(),
            vigente_desde=date(2026, 1, 1),
        )

        response = ejecutivo.post(LIST_URL, persona_payload(), format="json")

        assert response.status_code == HTTPStatus.CREATED
        assert Persona.objects.filter(rut="11111112-K").count() == 1
        assert Cliente.objects.get().persona == representante

    def test_requires_the_data_of_its_type(self, ejecutivo):
        response = ejecutivo.post(LIST_URL, {"tipo": "empresa"}, format="json")

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "empresa" in response.data

    def test_rejects_data_of_the_other_type(self, ejecutivo):
        payload = {**persona_payload(), "empresa": empresa_payload()["empresa"]}

        response = ejecutivo.post(LIST_URL, payload, format="json")

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "empresa" in response.data


class TestUpdate:
    def test_patch_edits_the_persona(self, ejecutivo):
        cliente = ClienteFactory.create()

        response = ejecutivo.patch(
            detail_url(cliente),
            {"persona": {"telefono": "+56 9 0000 0002"}, "activo": False},
            format="json",
        )

        assert response.status_code == HTTPStatus.OK
        cliente.refresh_from_db()
        assert cliente.parte.telefono == "+56 9 0000 0002"
        assert cliente.activo is False

    def test_type_cannot_change(self, ejecutivo):
        cliente = ClienteFactory.create()

        response = ejecutivo.patch(
            detail_url(cliente),
            {"tipo": "empresa"},
            format="json",
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_rut_cannot_take_another_record(self, ejecutivo):
        cliente = ClienteFactory.create()
        otra = PersonaFactory.create()

        response = ejecutivo.patch(
            detail_url(cliente),
            {"persona": {"rut": otra.rut}},
            format="json",
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "rut" in response.data["persona"]

    def test_keeping_its_own_rut_is_allowed(self, ejecutivo):
        cliente = ClienteFactory.create()

        response = ejecutivo.patch(
            detail_url(cliente),
            {"persona": {"rut": cliente.parte.rut}},
            format="json",
        )

        assert response.status_code == HTTPStatus.OK

    def test_put_and_delete_are_not_allowed(self, administrador):
        cliente = ClienteFactory.create()

        put = administrador.put(detail_url(cliente), persona_payload(), format="json")
        delete = administrador.delete(detail_url(cliente))

        assert put.status_code == HTTPStatus.METHOD_NOT_ALLOWED
        assert delete.status_code == HTTPStatus.METHOD_NOT_ALLOWED
        assert Cliente.objects.filter(pk=cliente.pk).exists()


class TestRead:
    def test_record_includes_the_representatives_of_a_company(self, ejecutivo):
        empresa = EmpresaFactory.create()
        representante = PersonaFactory.create()
        RepresentanteLegal.objects.create(
            persona=representante,
            empresa=empresa,
            vigente_desde=date(2026, 1, 1),
        )
        cliente = ClienteFactory.create(persona=None, empresa=empresa)

        response = ejecutivo.get(detail_url(cliente))

        assert response.status_code == HTTPStatus.OK
        assert response.data["persona"] is None
        assert response.data["empresa"]["razon_social"] == empresa.razon_social
        [fila] = response.data["representantes"]
        assert fila["rut"] == representante.rut
        assert fila["nombre"] == representante.nombre_completo

    def test_list_is_paginated_newest_first(self, ejecutivo):
        primero, segundo = ClienteFactory.create_batch(2)

        response = ejecutivo.get(LIST_URL)

        assert response.status_code == HTTPStatus.OK
        assert response.data["count"] == 2  # noqa: PLR2004
        assert [fila["id"] for fila in response.data["results"]] == [
            segundo.pk,
            primero.pk,
        ]
        fila = response.data["results"][0]
        assert fila["rut"] == segundo.parte.rut
        assert fila["nombre"] == segundo.nombre

    def test_list_filters_by_type(self, ejecutivo):
        ClienteFactory.create()
        empresa = ClienteFactory.create(persona=None, empresa=EmpresaFactory.create())

        response = ejecutivo.get(LIST_URL, {"tipo": "empresa"})

        assert [fila["id"] for fila in response.data["results"]] == [empresa.pk]


class TestSearch:
    @pytest.fixture
    def clientes(self, db) -> dict[str, Cliente]:
        return {
            "persona": ClienteFactory.create(
                persona=PersonaFactory.create(
                    rut="12345678-5",
                    nombres="Valentina",
                    apellido_paterno="Fuentes",
                ),
            ),
            "empresa": ClienteFactory.create(
                persona=None,
                empresa=EmpresaFactory.create(razon_social="Transportes Austral SpA"),
            ),
        }

    @pytest.mark.parametrize(
        ("buscar", "esperado"),
        [
            ("12.345.678-5", "persona"),
            ("12345678", "persona"),
            ("valentina fuentes", "persona"),
            ("austral", "empresa"),
            ("TRANSPORTES SpA", "empresa"),
        ],
    )
    def test_finds_by_rut_name_or_razon_social(
        self,
        ejecutivo,
        clientes,
        buscar,
        esperado,
    ):
        response = ejecutivo.get(LIST_URL, {"buscar": buscar})

        assert [fila["id"] for fila in response.data["results"]] == [
            clientes[esperado].pk,
        ]

    def test_finds_by_folio(self, ejecutivo, clientes):
        folio = clientes["empresa"].folio

        response = ejecutivo.get(LIST_URL, {"buscar": folio.lower()})

        assert [fila["folio"] for fila in response.data["results"]] == [folio]

    def test_every_word_must_match(self, ejecutivo, clientes):
        response = ejecutivo.get(LIST_URL, {"buscar": "valentina austral"})

        assert response.data["results"] == []


class TestPermissions:
    def test_a_user_without_a_role_is_denied(self, db):
        sin_rol = client_for(None)
        cliente = ClienteFactory.create()

        assert sin_rol.get(LIST_URL).status_code == HTTPStatus.FORBIDDEN
        assert sin_rol.get(detail_url(cliente)).status_code == HTTPStatus.FORBIDDEN
        assert (
            sin_rol.post(LIST_URL, persona_payload(), format="json").status_code
            == HTTPStatus.FORBIDDEN
        )

    def test_anonymous_is_denied(self, db):
        assert APIClient().get(LIST_URL).status_code == HTTPStatus.FORBIDDEN
