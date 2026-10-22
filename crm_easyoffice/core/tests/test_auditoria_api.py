"""Consulting the audit log (HU-31, RF-17, UC-13). Every value here is synthetic."""

from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from crm_easyoffice.clientes.models import RepresentanteLegal
from crm_easyoffice.clientes.tests.factories import ClienteFactory
from crm_easyoffice.clientes.tests.factories import CuentaClienteFactory
from crm_easyoffice.clientes.tests.factories import EmpresaFactory
from crm_easyoffice.clientes.tests.factories import PersonaFactory
from crm_easyoffice.clientes.tests.factories import RepresentanteLegalFactory
from crm_easyoffice.core.models import RegistroAuditoria
from crm_easyoffice.users.tests.factories import UserFactory

from .auditoria import api_como
from .auditoria import roles
from .auditoria import usuario_con_rol

pytestmark = pytest.mark.django_db

LISTA = reverse("auditoria:lista")
HISTORIAL = reverse("auditoria:historial")


@pytest.fixture
def administrador():
    return usuario_con_rol(roles.ADMINISTRADOR)


def historial_de(user, entidad: str, registro_id: int) -> list[dict]:
    respuesta = api_como(user).get(
        HISTORIAL,
        {"entidad": entidad, "registro_id": registro_id},
    )
    assert respuesta.status_code == HTTPStatus.OK
    return respuesta.json()["results"]


class TestAcceso:
    @pytest.mark.parametrize(
        "url",
        [LISTA, f"{HISTORIAL}?entidad=clientes.cliente&registro_id=1"],
    )
    def test_only_the_administrador_consults_it(self, url, administrador):
        ejecutivo = api_como(usuario_con_rol(roles.EJECUTIVO))
        cliente = api_como(CuentaClienteFactory.create().user)

        assert api_como(administrador).get(url).status_code == HTTPStatus.OK
        assert ejecutivo.get(url).status_code == HTTPStatus.FORBIDDEN
        assert cliente.get(url).status_code == HTTPStatus.FORBIDDEN
        assert APIClient().get(url).status_code == HTTPStatus.FORBIDDEN

    def test_there_is_no_way_to_write(self, administrador):
        PersonaFactory.create()
        entrada = RegistroAuditoria.objects.first()
        client = api_como(administrador)

        for metodo in (client.post, client.put, client.patch, client.delete):
            assert (
                metodo(LISTA, {}, format="json").status_code
                == HTTPStatus.METHOD_NOT_ALLOWED
            )
        assert RegistroAuditoria.objects.get(pk=entrada.pk).entidad == entrada.entidad


class TestLista:
    def test_rows_carry_readable_names(self, administrador):
        cliente = ClienteFactory.create()
        ejecutivo = usuario_con_rol(roles.EJECUTIVO)
        api_como(ejecutivo).patch(
            reverse("api:cliente-detail", args=[cliente.pk]),
            {"activo": False},
            format="json",
        )

        respuesta = api_como(administrador).get(
            LISTA,
            {
                "entidad": "clientes.cliente",
                "registro_id": cliente.pk,
                "accion": "modificar",
            },
        )

        assert respuesta.status_code == HTTPStatus.OK
        # Newest first; the oldest one is the code assigned on creation.
        fila = respuesta.json()["results"][0]
        assert fila["usuario_nombre"] == ejecutivo.name
        assert fila["entidad_nombre"] == "cliente"
        assert fila["registro_nombre"] == cliente.codigo
        assert fila["valor_anterior"] == {"activo": True}
        assert fila["valor_nuevo"] == {"activo": False}
        assert fila["origen"] == "api"

    def test_the_system_has_no_user_name(self, administrador):
        persona = PersonaFactory.create()

        [fila] = historial_de(administrador, "clientes.persona", persona.pk)

        assert fila["usuario"] is None
        assert fila["usuario_nombre"] is None
        assert fila["registro_nombre"] == persona.rut

    def test_filters(self, administrador):
        otro = UserFactory.create()
        PersonaFactory.create()
        RegistroAuditoria.objects.create(
            usuario=otro,
            origen="portal",
            accion="inicio_sesion",
            entidad="users.user",
            registro_id=otro.pk,
        )
        client = api_como(administrador)

        def contar(**filtros) -> int:
            respuesta = client.get(LISTA, filtros)
            assert respuesta.status_code == HTTPStatus.OK, respuesta.json()
            return respuesta.json()["count"]

        total = contar()
        assert contar(usuario=otro.pk) == 1
        assert contar(accion="inicio_sesion", origen="portal") == 1
        assert contar(origen="admin") == 0
        hoy = timezone.localdate()
        assert contar(desde=hoy.isoformat(), hasta=hoy.isoformat()) == total
        assert contar(hasta=(hoy - timedelta(days=1)).isoformat()) == 0

    @pytest.mark.parametrize(
        "filtros",
        [
            {"registro_id": 1},
            {"accion": "borrar"},
            {"desde": "2026-10-02", "hasta": "2026-10-01"},
            {"desde": "ayer"},
        ],
    )
    def test_invalid_filters_are_rejected(self, administrador, filtros):
        assert (
            api_como(administrador).get(LISTA, filtros).status_code
            == HTTPStatus.BAD_REQUEST
        )

    def test_the_query_count_does_not_grow_with_the_page(
        self,
        administrador,
        django_assert_max_num_queries,
    ):
        for _ in range(3):
            ClienteFactory.create()
        client = api_como(administrador)
        client.get(LISTA)
        for _ in range(10):
            ClienteFactory.create()

        # Count, page, and one query per entity named on the page.
        with django_assert_max_num_queries(8):
            respuesta = client.get(LISTA)

        assert respuesta.status_code == HTTPStatus.OK
        assert len(respuesta.json()["results"]) == 25  # noqa: PLR2004


class TestHistorial:
    def test_a_clients_history_includes_its_persona_representatives_and_account(
        self,
        administrador,
    ):
        empresa = EmpresaFactory.create()
        cliente = ClienteFactory.create(persona=None, empresa=empresa)
        representacion = RepresentanteLegalFactory.create(empresa=empresa)
        representacion.persona.domicilio = "Calle Sintética 123"
        representacion.persona.save()
        cuenta = CuentaClienteFactory.create(cliente=cliente)
        otro = ClienteFactory.create()

        filas = historial_de(administrador, "clientes.cliente", cliente.pk)

        vistos = {(f["entidad"], f["registro_id"]) for f in filas}
        assert ("clientes.cliente", cliente.pk) in vistos
        assert ("clientes.empresa", empresa.pk) in vistos
        assert ("clientes.representantelegal", representacion.pk) in vistos
        assert ("clientes.persona", representacion.persona_id) in vistos
        assert ("clientes.cuentacliente", cuenta.pk) in vistos
        assert ("clientes.cliente", otro.pk) not in vistos

    def test_a_deleted_representative_stays_in_the_history(self, administrador):
        empresa = EmpresaFactory.create()
        cliente = ClienteFactory.create(persona=None, empresa=empresa)
        representacion = RepresentanteLegalFactory.create(empresa=empresa)
        pk = representacion.pk
        RepresentanteLegal.objects.filter(pk=pk).delete()

        filas = historial_de(administrador, "clientes.cliente", cliente.pk)

        acciones = [
            f["accion"] for f in filas if f["entidad"] == "clientes.representantelegal"
        ]
        assert sorted(acciones) == ["crear", "eliminar"]

    def test_requires_the_record(self, administrador):
        respuesta = api_como(administrador).get(
            HISTORIAL,
            {"entidad": "clientes.cliente"},
        )

        assert respuesta.status_code == HTTPStatus.BAD_REQUEST


class TestAdmin:
    def test_the_admin_is_read_only_even_for_a_superuser(self, admin_client):
        PersonaFactory.create()
        entrada = RegistroAuditoria.objects.first()
        cambio = reverse("admin:core_registroauditoria_change", args=[entrada.pk])

        assert admin_client.get(
            reverse("admin:core_registroauditoria_changelist"),
        ).status_code == (HTTPStatus.OK)
        assert admin_client.get(cambio).status_code == HTTPStatus.OK
        assert admin_client.get(
            reverse("admin:core_registroauditoria_add"),
        ).status_code == (HTTPStatus.FORBIDDEN)
        admin_client.post(cambio, {"entidad": "alterada"})
        borrar = reverse("admin:core_registroauditoria_delete", args=[entrada.pk])
        assert (
            admin_client.post(borrar, {"post": "yes"}).status_code
            == HTTPStatus.FORBIDDEN
        )
        assert RegistroAuditoria.objects.get(pk=entrada.pk).entidad == entrada.entidad
