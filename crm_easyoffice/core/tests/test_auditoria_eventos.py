"""Sign-ins, sign-outs and failed attempts are recorded (RN-36, RS-04).

Every name and address here is synthetic.
"""

from __future__ import annotations

from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse

from crm_easyoffice.clientes.tests.factories import CuentaClienteFactory
from crm_easyoffice.core.auditoria.eventos import registrar_evento
from crm_easyoffice.core.models import RegistroAuditoria
from crm_easyoffice.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

PASSWORD = "synthetic-Pass-123"  # noqa: S105
WRONG_PASSWORD = "clave-equivocada"  # noqa: S105
Accion = RegistroAuditoria.Accion
Origen = RegistroAuditoria.Origen


def eventos(accion: str):
    return RegistroAuditoria.objects.filter(accion=accion).order_by("pk")


def web_login(browser: Client, email: str, password: str = PASSWORD):
    return browser.post(
        reverse("auth:login"),
        {"email": email, "password": password},
        content_type="application/json",
    )


class TestInicioDeSesion:
    def test_a_staff_login_is_recorded(self):
        usuario = UserFactory.create(password=PASSWORD)

        assert web_login(Client(), usuario.email).status_code == HTTPStatus.OK

        evento = eventos(Accion.INICIO_SESION).last()
        assert evento.usuario == usuario
        assert evento.entidad == "users.user"
        assert evento.registro_id == usuario.pk
        assert evento.origen == Origen.API
        assert evento.direccion_ip == "127.0.0.1"

    def test_a_portal_client_login_is_recorded_as_portal(self):
        cuenta = CuentaClienteFactory.create(user__password=PASSWORD)

        assert web_login(Client(), cuenta.user.email).status_code == HTTPStatus.OK

        evento = eventos(Accion.INICIO_SESION).last()
        assert evento.usuario == cuenta.user
        assert evento.origen == Origen.PORTAL

    def test_a_failed_login_is_recorded_without_the_password(self):
        usuario = UserFactory.create(password=PASSWORD)

        respuesta = web_login(Client(), usuario.email, password=WRONG_PASSWORD)

        assert respuesta.status_code == HTTPStatus.BAD_REQUEST
        evento = eventos(Accion.INICIO_SESION_FALLIDO).last()
        assert evento.usuario is None
        assert evento.registro_id == usuario.pk
        assert evento.valor_nuevo == {"email": usuario.email}
        assert WRONG_PASSWORD not in str(evento.valor_nuevo)

    def test_a_failed_login_for_an_unknown_address_is_recorded(self):
        web_login(Client(), "nadie@example.test")

        evento = eventos(Accion.INICIO_SESION_FALLIDO).last()
        assert evento.registro_id is None
        assert evento.valor_nuevo == {"email": "nadie@example.test"}

    def test_a_logout_is_recorded(self):
        usuario = UserFactory.create(password=PASSWORD)
        browser = Client()
        web_login(browser, usuario.email)

        browser.post(reverse("auth:logout"))

        evento = eventos(Accion.CIERRE_SESION).last()
        assert evento.usuario == usuario
        assert evento.origen == Origen.API

    def test_an_admin_login_and_failure_are_recorded_as_admin(self):
        usuario = UserFactory.create(
            password=PASSWORD,
            is_staff=True,
            is_superuser=True,
        )
        browser = Client()

        browser.post(
            reverse("admin:login"),
            {"username": usuario.email, "password": "x"},
        )
        browser.post(
            reverse("admin:login"),
            {"username": usuario.email, "password": PASSWORD},
        )

        fallido = eventos(Accion.INICIO_SESION_FALLIDO).last()
        inicio = eventos(Accion.INICIO_SESION).last()
        assert fallido.origen == inicio.origen == Origen.ADMIN
        assert inicio.usuario == usuario


class TestRegistrarEvento:
    def test_without_a_request_the_event_is_the_systems(self):
        evento = registrar_evento(
            Accion.DESCARGA_DOCUMENTO,
            entidad="documentos.documento",
            registro_id=1,
            datos={"archivo": "pdf"},
        )

        assert evento.origen == Origen.SISTEMA
        assert evento.usuario is None
        assert evento.valor_nuevo == {"archivo": "pdf"}
