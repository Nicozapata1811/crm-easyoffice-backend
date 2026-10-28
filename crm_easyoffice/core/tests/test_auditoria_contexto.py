"""Who, from where and through which channel each change is recorded (RF-15).

Every name, RUT and value here is synthetic.
"""

from __future__ import annotations

import threading
from http import HTTPStatus
from types import SimpleNamespace
from typing import TYPE_CHECKING
from typing import Any

import pytest
from django.db import connection
from django.db import transaction
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import reverse

from crm_easyoffice.clientes.tests.factories import ClienteFactory
from crm_easyoffice.clientes.tests.factories import PersonaFactory
from crm_easyoffice.configuracion.models import Marca
from crm_easyoffice.core.auditoria.contexto import AplicadorContexto
from crm_easyoffice.core.auditoria.contexto import Contexto
from crm_easyoffice.core.auditoria.contexto import contexto_auditoria
from crm_easyoffice.core.auditoria.contexto import origen_de
from crm_easyoffice.core.middleware import AuditoriaMiddleware
from crm_easyoffice.core.models import RegistroAuditoria
from crm_easyoffice.tramites.tests.factories import cuenta_empresa
from crm_easyoffice.tramites.tests.factories import payload_domicilio
from crm_easyoffice.tramites.tests.factories import preparar_domicilio
from crm_easyoffice.users.tests.factories import UserFactory
from crm_easyoffice.ventas.models import OrdenPago
from crm_easyoffice.ventas.models import Venta
from crm_easyoffice.ventas.tasks import sincronizar_orden

from .auditoria import api_como
from .auditoria import roles
from .auditoria import ultima
from .auditoria import usuario_con_rol

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest

pytestmark = pytest.mark.django_db

Origen = RegistroAuditoria.Origen


def peticion(user: Any, ruta: str = "/api/clientes/") -> HttpRequest:
    request = RequestFactory().get(ruta, REMOTE_ADDR="192.0.2.10")
    request.user = user
    return request


@pytest.fixture
def fijaciones(monkeypatch) -> list[tuple[str, str, str]]:
    """Every set_config the wrapper sends, in order."""
    enviadas: list[tuple[str, str, str]] = []
    original = AplicadorContexto.fijar

    def espia(cursor, parametros):
        enviadas.append(parametros)
        original(cursor, parametros)

    monkeypatch.setattr(AplicadorContexto, "fijar", staticmethod(espia))
    return enviadas


class TestCanales:
    def test_staff_api_records_the_user_ip_and_channel(self):
        ejecutivo = usuario_con_rol(roles.EJECUTIVO)
        cliente = ClienteFactory.create()

        respuesta = api_como(ejecutivo).patch(
            reverse("api:cliente-detail", args=[cliente.pk]),
            {"persona": {"telefono": "+56 9 0000 0002"}},
            format="json",
        )

        assert respuesta.status_code == HTTPStatus.OK
        entrada = ultima("clientes.persona", cliente.persona_id)
        assert entrada.valor_nuevo == {"telefono": "+56 9 0000 0002"}
        assert entrada.usuario == ejecutivo
        assert entrada.origen == Origen.API
        assert entrada.direccion_ip == "127.0.0.1"

    def test_portal_records_the_clients_own_user(self):
        cuenta = cuenta_empresa()
        sucursal = preparar_domicilio("LF")

        respuesta = api_como(cuenta.user).post(
            reverse("portal:tramite-crear-domicilio"),
            payload_domicilio(cuenta.cliente, sucursal),
            format="json",
        )

        assert respuesta.status_code == HTTPStatus.CREATED
        entrada = ultima("tramites.tramite", respuesta.json()["id"])
        assert entrada.usuario == cuenta.user
        assert entrada.origen == Origen.PORTAL

    def test_admin_records_the_admin_user(self, admin_client, admin_user):
        marca = Marca.objects.create(nombre="MARCA SINTÉTICA")

        respuesta = admin_client.post(
            reverse("admin:configuracion_marca_change", args=[marca.pk]),
            {"nombre": "MARCA RENOMBRADA", "activa": "on", "cuenta_pago_default": ""},
        )

        assert respuesta.status_code == HTTPStatus.FOUND
        entrada = ultima("configuracion.marca", marca.pk)
        assert entrada.valor_nuevo == {"nombre": "MARCA RENOMBRADA"}
        assert entrada.usuario == admin_user
        assert entrada.origen == Origen.ADMIN

    def test_a_celery_task_is_the_systems_even_inside_a_request(self):
        venta = Venta.objects.create(cliente=cuenta_empresa().cliente, total=1000)
        orden = OrdenPago.objects.create(
            venta=venta,
            proveedor="simulated",
            monto=1000,
            id_externo="sim-0001",
            estado=OrdenPago.Estado.PENDIENTE,
        )
        ejecutivo = usuario_con_rol(roles.EJECUTIVO)

        with contexto_auditoria(Contexto(request=peticion(ejecutivo))):
            antes = PersonaFactory.create()
            sincronizar_orden.apply(args=[orden.pk])
            despues = PersonaFactory.create()

        sincronizada = ultima("ventas.ordenpago", orden.pk)
        assert "sincronizada_en" in sincronizada.valor_nuevo
        assert sincronizada.origen == Origen.SISTEMA
        assert sincronizada.usuario is None
        assert ultima("clientes.persona", antes.pk).usuario == ejecutivo
        assert ultima("clientes.persona", despues.pk).usuario == ejecutivo


class TestAlcance:
    def test_a_rolled_back_savepoint_does_not_lose_the_context(self):
        usuario = UserFactory.create()

        with (
            contexto_auditoria(Contexto(request=peticion(usuario))),
            transaction.atomic(),
        ):
            try:
                with transaction.atomic():
                    PersonaFactory.create()
                    raise RuntimeError  # noqa: TRY301
            except RuntimeError:
                pass
            persona = PersonaFactory.create()

        assert ultima("clientes.persona", persona.pk).usuario == usuario

    def test_after_the_request_nothing_is_left_behind(self):
        usuario = UserFactory.create()

        with contexto_auditoria(Contexto(request=peticion(usuario))):
            PersonaFactory.create()
        persona = PersonaFactory.create()

        entrada = ultima("clientes.persona", persona.pk)
        assert entrada.usuario is None
        assert entrada.origen == Origen.SISTEMA

    def test_the_context_is_set_once_per_transaction(self, fijaciones):
        usuario = UserFactory.create()

        with (
            contexto_auditoria(Contexto(request=peticion(usuario))),
            transaction.atomic(),
        ):
            persona = PersonaFactory.create()
            persona.telefono = "+56 9 0000 0003"
            persona.save()
            PersonaFactory.create()

        assert fijaciones == [(str(usuario.pk), "192.0.2.10", Origen.API)]

    def test_reads_never_set_the_context(self, fijaciones):
        ClienteFactory.create_batch(3)
        fijaciones.clear()

        respuesta = api_como(usuario_con_rol(roles.EJECUTIVO)).get(
            reverse("api:cliente-list"),
        )

        assert respuesta.status_code == HTTPStatus.OK
        assert fijaciones == []


# The tests below run on a connection of their own, outside the test's
# transaction, so each request really commits as in production. They write
# only to a temporary table: nothing they do outlives the connection.


def en_conexion_propia(funcion: Callable[[], Any]) -> Any:
    resultado: dict[str, Any] = {}

    def correr() -> None:
        try:
            with connection.cursor() as cursor:
                cursor.execute("CREATE TEMP TABLE prueba_auditoria (x int)")
            resultado["valor"] = funcion()
        except BaseException as error:  # noqa: BLE001
            resultado["error"] = error
        finally:
            connection.close()

    hilo = threading.Thread(target=correr)
    hilo.start()
    hilo.join()
    if "error" in resultado:
        raise resultado["error"]
    return resultado["valor"]


def usuario_en_sesion(pk: int) -> Any:
    """A signed-in user that never reaches the database."""
    return SimpleNamespace(pk=pk, is_authenticated=True)


def usuario_fijado(cursor) -> str | None:
    cursor.execute("SELECT current_setting('app.usuario_id', true)")
    return cursor.fetchone()[0] or None


def vista_que_escribe(vistos: list[str | None], *, atomica: bool) -> Callable:
    def escribir() -> None:
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO prueba_auditoria VALUES (1)")
            vistos.append(usuario_fijado(cursor))

    def vista(request: HttpRequest) -> HttpResponse:
        if atomica:
            with transaction.atomic():
                escribir()
        else:
            escribir()
        return HttpResponse()

    return vista


class TestConexionReutilizada:
    def test_a_request_never_sees_the_previous_users_context(self):
        def dos_peticiones_y_una_tarea() -> list[str | None]:
            vistos: list[str | None] = []
            middleware = AuditoriaMiddleware(vista_que_escribe(vistos, atomica=True))
            middleware(peticion(usuario_en_sesion(41)))
            middleware(peticion(usuario_en_sesion(42)))
            with transaction.atomic(), connection.cursor() as cursor:
                vistos.append(usuario_fijado(cursor))
                cursor.execute("INSERT INTO prueba_auditoria VALUES (2)")
                vistos.append(usuario_fijado(cursor))
            return vistos

        assert en_conexion_propia(dos_peticiones_y_una_tarea) == [
            "41",
            "42",
            None,
            None,
        ]

    def test_a_request_without_a_transaction_records_no_user(self, fijaciones):
        def sin_transaccion() -> list[str | None]:
            vistos: list[str | None] = []
            middleware = AuditoriaMiddleware(vista_que_escribe(vistos, atomica=False))
            middleware(peticion(usuario_en_sesion(41)))
            return vistos

        assert en_conexion_propia(sin_transaccion) == [None]
        assert fijaciones == []


@pytest.mark.parametrize(
    ("ruta", "origen"),
    [
        ("/admin/clientes/persona/1/change/", Origen.ADMIN),
        ("/api/portal/tramites/", Origen.PORTAL),
        ("/api/pagos/webhooks/klap/confirmacion/", Origen.SISTEMA),
        ("/api/firma/webhooks/sandbox/", Origen.SISTEMA),
        ("/api/clientes/", Origen.API),
    ],
)
def test_the_channel_comes_from_the_route(ruta, origen):
    request = peticion(usuario_en_sesion(41), ruta)

    assert origen_de(request, request.user) == origen
