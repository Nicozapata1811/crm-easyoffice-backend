"""Expiry alerts API and the contracts of a client. All data is synthetic."""

from __future__ import annotations

import importlib
from datetime import timedelta
from http import HTTPStatus

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from crm_easyoffice.clientes.tests.factories import ClienteFactory
from crm_easyoffice.contratos.models import AlertaVencimiento
from crm_easyoffice.contratos.models import Contrato
from crm_easyoffice.contratos.services import asignar_responsable
from crm_easyoffice.contratos.services import gestionar_alerta
from crm_easyoffice.contratos.tests.factories import nuevo_contrato
from crm_easyoffice.core.tests.auditoria import api_como
from crm_easyoffice.core.tests.auditoria import entradas
from crm_easyoffice.core.tests.auditoria import usuario_con_rol
from crm_easyoffice.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

seed = importlib.import_module("crm_easyoffice.core.migrations.0002_seed_roles")

LISTA = reverse("api:alerta-vencimiento-list")
RESUMEN = reverse("api:alerta-vencimiento-resumen")
CONTRATOS = reverse("api:contrato-list")
EJECUTIVOS = reverse("api:contrato-ejecutivos")


def gestionar_url(alerta: AlertaVencimiento) -> str:
    return reverse("api:alerta-vencimiento-gestionar", kwargs={"pk": alerta.pk})


def responsable_url(contrato: Contrato) -> str:
    return reverse("api:contrato-responsable", kwargs={"pk": contrato.pk})


def alerta(
    responsable=None,
    *,
    dias: int = 10,
    umbral: int = 15,
    **datos,
) -> AlertaVencimiento:
    contrato = nuevo_contrato(ejecutivo=responsable, **datos)
    vencimiento = timezone.localdate() + timedelta(days=dias)
    Contrato.objects.filter(pk=contrato.pk).update(fecha_vencimiento=vencimiento)
    return AlertaVencimiento.objects.create(
        contrato=contrato,
        umbral_dias=umbral,
        fecha_vencimiento=vencimiento,
    )


def ids(respuesta) -> list[int]:
    assert respuesta.status_code == HTTPStatus.OK, respuesta.json()
    return [fila["id"] for fila in respuesta.json()["results"]]


@pytest.fixture
def ejecutivo():
    return usuario_con_rol(seed.EJECUTIVO)


@pytest.fixture
def otro_ejecutivo():
    return usuario_con_rol(seed.EJECUTIVO)


@pytest.fixture
def administrador():
    return usuario_con_rol(seed.ADMINISTRADOR)


class TestVisibilidad:
    def test_an_executive_sees_their_own_and_those_without_a_responsible(
        self,
        ejecutivo,
        otro_ejecutivo,
    ):
        propia = alerta(ejecutivo)
        sin_responsable = alerta()
        alerta(otro_ejecutivo)

        assert set(ids(api_como(ejecutivo).get(LISTA))) == {
            propia.pk,
            sin_responsable.pk,
        }

    def test_the_administrador_sees_all(self, administrador, ejecutivo):
        todas = {alerta(ejecutivo).pk, alerta().pk, alerta(administrador).pk}

        assert set(ids(api_como(administrador).get(LISTA))) == todas

    def test_it_follows_a_change_of_responsible(self, ejecutivo, otro_ejecutivo):
        fila = alerta(otro_ejecutivo)
        cliente = api_como(ejecutivo)
        assert ids(cliente.get(LISTA)) == []

        asignar_responsable(fila.contrato, ejecutivo)

        assert ids(cliente.get(LISTA)) == [fila.pk]

    @pytest.mark.parametrize("url", [LISTA, RESUMEN])
    def test_without_a_role_there_is_no_access(self, url):
        respuesta = api_como(UserFactory.create()).get(url)

        assert respuesta.status_code == HTTPStatus.FORBIDDEN

    def test_someone_elses_alert_cannot_be_handled(self, ejecutivo, otro_ejecutivo):
        fila = alerta(otro_ejecutivo)

        respuesta = api_como(ejecutivo).post(gestionar_url(fila), {})

        assert respuesta.status_code == HTTPStatus.NOT_FOUND
        fila.refresh_from_db()
        assert fila.estado == AlertaVencimiento.Estado.PENDIENTE

    def test_a_user_without_the_permission_cannot_handle(self):
        fila = alerta()

        respuesta = api_como(UserFactory.create()).post(gestionar_url(fila), {})

        assert respuesta.status_code == HTTPStatus.FORBIDDEN


class TestLista:
    def test_a_row_says_what_the_screen_shows(self, administrador, ejecutivo):
        fila = alerta(ejecutivo, dias=10, umbral=15)

        datos = api_como(administrador).get(LISTA).json()["results"][0]

        contrato = fila.contrato
        assert datos["folio"] == contrato.folio
        assert datos["contrato"] == contrato.pk
        assert datos["renovacion_automatica"] is True
        assert datos["cliente"] == {
            "id": contrato.cliente_id,
            "codigo": contrato.cliente.codigo,
            "nombre": contrato.cliente.nombre,
        }
        assert datos["servicios"] == ["Domicilio tributario"]
        assert datos["ejecutivo_responsable"] == {
            "id": ejecutivo.pk,
            "nombre": ejecutivo.name,
        }
        assert datos["umbral_dias"] == 15  # noqa: PLR2004
        assert datos["dias_restantes"] == 10  # noqa: PLR2004
        assert datos["estado"] == "pendiente"
        assert datos["gestionada_por_nombre"] is None

    def test_no_responsible_reads_null(self, administrador):
        alerta()

        datos = api_como(administrador).get(LISTA).json()["results"][0]

        assert datos["ejecutivo_responsable"] is None

    def test_days_left_go_negative_once_past(self, administrador):
        alerta(dias=-2)

        datos = api_como(administrador).get(LISTA).json()["results"][0]

        assert datos["dias_restantes"] == -2  # noqa: PLR2004

    def test_soonest_expiry_first(self, administrador):
        lejana = alerta(dias=50, umbral=60)
        cercana = alerta(dias=3, umbral=7)

        assert ids(api_como(administrador).get(LISTA)) == [cercana.pk, lejana.pk]

    def test_filter_by_state(self, administrador):
        pendiente = alerta()
        gestionada = gestionar_alerta(alerta(), administrador)
        cliente = api_como(administrador)

        assert ids(cliente.get(LISTA, {"estado": "pendiente"})) == [pendiente.pk]
        assert ids(cliente.get(LISTA, {"estado": "gestionada"})) == [gestionada.pk]

    def test_mine_leaves_out_those_without_a_responsible(self, ejecutivo):
        propia = alerta(ejecutivo)
        alerta()

        assert ids(api_como(ejecutivo).get(LISTA, {"mias": "true"})) == [propia.pk]

    def test_filter_by_threshold(self, administrador):
        treinta = alerta(umbral=30)
        alerta(umbral=7)

        respuesta = api_como(administrador).get(LISTA, {"umbral": 30})

        assert ids(respuesta) == [treinta.pk]

    def test_filter_by_expiry_range_both_ends_inclusive(self, administrador):
        hoy = timezone.localdate()
        alerta(dias=1)
        dentro = [alerta(dias=2).pk, alerta(dias=4).pk]
        alerta(dias=5)

        respuesta = api_como(administrador).get(
            LISTA,
            {
                "vence_desde": str(hoy + timedelta(days=2)),
                "vence_hasta": str(hoy + timedelta(days=4)),
            },
        )

        assert ids(respuesta) == dentro

    @pytest.mark.parametrize(
        ("filtros", "campo"),
        [
            ({"estado": "otro"}, "estado"),
            ({"umbral": "x"}, "umbral"),
            ({"umbral": "0"}, "umbral"),
            ({"vence_desde": "ayer"}, "vence_desde"),
            ({"vence_desde": "2027-01-02", "vence_hasta": "2027-01-01"}, "vence_hasta"),
        ],
    )
    def test_invalid_filters_answer_400_on_their_field(
        self,
        administrador,
        filtros,
        campo,
    ):
        respuesta = api_como(administrador).get(LISTA, filtros)

        assert respuesta.status_code == HTTPStatus.BAD_REQUEST
        assert campo in respuesta.json()

    def test_queries_do_not_grow_with_the_rows(self, administrador, ejecutivo):
        alerta(ejecutivo)
        cliente = api_como(administrador)
        cliente.get(LISTA)  # Fills the user's permission cache.

        with CaptureQueriesContext(connection) as una_fila:
            assert len(ids(cliente.get(LISTA))) == 1

        for _ in range(5):
            gestionar_alerta(alerta(ejecutivo), administrador, "Nota de prueba")

        with CaptureQueriesContext(connection) as seis_filas:
            assert len(ids(cliente.get(LISTA))) == 6  # noqa: PLR2004

        assert len(seis_filas) == len(una_fila)
        # Count, page and the contracts' lines, in the request's savepoint.
        assert len(una_fila) == 5  # noqa: PLR2004


class TestGestionar:
    def test_it_records_who_when_and_the_note(self, ejecutivo):
        fila = alerta(ejecutivo)

        respuesta = api_como(ejecutivo).post(
            gestionar_url(fila),
            {"nota": "  El cliente renovará por transferencia.  "},
        )

        assert respuesta.status_code == HTTPStatus.OK, respuesta.json()
        fila.refresh_from_db()
        assert fila.estado == AlertaVencimiento.Estado.GESTIONADA
        assert fila.gestionada_por == ejecutivo
        assert fila.gestionada_en is not None
        assert fila.nota == "El cliente renovará por transferencia."
        datos = respuesta.json()
        assert datos["estado"] == "gestionada"
        assert datos["gestionada_por_nombre"] == ejecutivo.name

    def test_the_note_is_optional(self, ejecutivo):
        fila = alerta(ejecutivo)

        respuesta = api_como(ejecutivo).post(gestionar_url(fila), {})

        assert respuesta.status_code == HTTPStatus.OK
        fila.refresh_from_db()
        assert fila.nota == ""

    def test_a_long_note_is_refused(self, ejecutivo):
        fila = alerta(ejecutivo)

        respuesta = api_como(ejecutivo).post(gestionar_url(fila), {"nota": "x" * 1001})

        assert respuesta.status_code == HTTPStatus.BAD_REQUEST
        assert "nota" in respuesta.json()

    def test_a_second_time_answers_409_and_changes_nothing(
        self,
        ejecutivo,
        administrador,
    ):
        fila = alerta(ejecutivo)
        api_como(ejecutivo).post(gestionar_url(fila), {"nota": "Primera"})

        respuesta = api_como(administrador).post(
            gestionar_url(fila),
            {"nota": "Segunda"},
        )

        assert respuesta.status_code == HTTPStatus.CONFLICT
        assert respuesta.json()["codigo"] == "alerta_ya_gestionada"
        fila.refresh_from_db()
        assert (fila.gestionada_por, fila.nota) == (ejecutivo, "Primera")

    def test_there_is_no_way_back_to_pending(self, ejecutivo):
        fila = alerta(ejecutivo)
        cliente = api_como(ejecutivo)

        assert (
            cliente.patch(gestionar_url(fila), {"estado": "pendiente"}).status_code
            == HTTPStatus.METHOD_NOT_ALLOWED
        )
        detalle = f"{LISTA}{fila.pk}/"
        assert cliente.put(detalle, {}).status_code == HTTPStatus.NOT_FOUND
        assert cliente.delete(detalle).status_code == HTTPStatus.NOT_FOUND

    def test_it_is_audited(self, ejecutivo):
        fila = alerta(ejecutivo)

        api_como(ejecutivo).post(gestionar_url(fila), {"nota": "Hablé con el cliente"})

        creacion, cambio = entradas("contratos.alertavencimiento", fila.pk)
        assert creacion.accion == "crear"
        assert cambio.valor_nuevo["estado"] == "gestionada"
        assert cambio.valor_nuevo["nota"] == "Hablé con el cliente"

    def test_the_contract_history_includes_its_alerts(self, administrador):
        fila = alerta()

        respuesta = api_como(administrador).get(
            "/api/auditoria/historial/",
            {"entidad": "contratos.contrato", "registro_id": fila.contrato_id},
        )

        assert respuesta.status_code == HTTPStatus.OK
        assert "contratos.alertavencimiento" in {
            entrada["entidad"] for entrada in respuesta.json()["results"]
        }


class TestResumen:
    def test_it_counts_the_pending_alerts_the_user_sees(
        self,
        ejecutivo,
        otro_ejecutivo,
    ):
        alerta(ejecutivo, umbral=30)
        alerta(umbral=7)
        alerta(otro_ejecutivo, umbral=60)
        gestionar_alerta(alerta(ejecutivo, umbral=15), ejecutivo)

        datos = api_como(ejecutivo).get(RESUMEN).json()

        assert datos == {"pendientes": 2, "umbrales": [30, 15, 7]}

    def test_handling_one_takes_it_off_the_count(self, ejecutivo):
        fila = alerta(ejecutivo)
        cliente = api_como(ejecutivo)
        assert cliente.get(RESUMEN).json()["pendientes"] == 1

        cliente.post(gestionar_url(fila), {})

        assert cliente.get(RESUMEN).json()["pendientes"] == 0


class TestContratosDeUnCliente:
    def test_the_filter_returns_only_that_clients_contracts(self, ejecutivo):
        cliente = ClienteFactory.create()
        propio = nuevo_contrato(cliente=cliente)
        nuevo_contrato()

        respuesta = api_como(ejecutivo).get(CONTRATOS, {"cliente": cliente.pk})

        assert ids(respuesta) == [propio.pk]

    def test_it_carries_days_left_and_the_responsibles_name(self, ejecutivo):
        contrato = nuevo_contrato(ejecutivo=ejecutivo)
        Contrato.objects.filter(pk=contrato.pk).update(
            fecha_vencimiento=timezone.localdate() + timedelta(days=9),
        )

        datos = (
            api_como(ejecutivo)
            .get(CONTRATOS, {"cliente": contrato.cliente_id})
            .json()["results"][0]
        )

        assert datos["dias_restantes"] == 9  # noqa: PLR2004
        assert datos["ejecutivo_responsable"] == ejecutivo.pk
        assert datos["ejecutivo_responsable_nombre"] == ejecutivo.name
        assert [linea["nombre"] for linea in datos["servicios"]] == [
            "Domicilio tributario",
        ]

    def test_days_left_only_for_a_contract_in_force(self, ejecutivo):
        contrato = nuevo_contrato(borrador=True)

        datos = (
            api_como(ejecutivo)
            .get(CONTRATOS, {"cliente": contrato.cliente_id})
            .json()["results"][0]
        )

        assert datos["dias_restantes"] is None
        assert datos["ejecutivo_responsable_nombre"] is None

    def test_a_user_without_the_permission_cannot_list_them(self):
        respuesta = api_como(UserFactory.create()).get(CONTRATOS, {"cliente": 1})

        assert respuesta.status_code == HTTPStatus.FORBIDDEN


class TestResponsable:
    def test_the_administrador_sets_it(self, administrador, ejecutivo):
        contrato = nuevo_contrato()

        respuesta = api_como(administrador).post(
            responsable_url(contrato),
            {"ejecutivo": ejecutivo.pk},
        )

        assert respuesta.status_code == HTTPStatus.OK, respuesta.json()
        assert respuesta.json()["ejecutivo_responsable_nombre"] == ejecutivo.name
        contrato.refresh_from_db()
        assert contrato.ejecutivo_responsable == ejecutivo

    def test_the_administrador_changes_it(
        self,
        administrador,
        ejecutivo,
        otro_ejecutivo,
    ):
        contrato = nuevo_contrato(ejecutivo=ejecutivo)

        api_como(administrador).post(
            responsable_url(contrato),
            {"ejecutivo": otro_ejecutivo.pk},
        )

        contrato.refresh_from_db()
        assert contrato.ejecutivo_responsable == otro_ejecutivo

    def test_an_executive_cannot_even_with_change_contrato(self, ejecutivo):
        assert ejecutivo.has_perm("contratos.change_contrato")
        contrato = nuevo_contrato()

        respuesta = api_como(ejecutivo).post(
            responsable_url(contrato),
            {"ejecutivo": ejecutivo.pk},
        )

        assert respuesta.status_code == HTTPStatus.FORBIDDEN
        contrato.refresh_from_db()
        assert contrato.ejecutivo_responsable is None

    def test_only_someone_who_handles_alerts_can_be_responsible(self, administrador):
        contrato = nuevo_contrato()

        respuesta = api_como(administrador).post(
            responsable_url(contrato),
            {"ejecutivo": UserFactory.create().pk},
        )

        assert respuesta.status_code == HTTPStatus.BAD_REQUEST
        assert "ejecutivo" in respuesta.json()

    def test_an_inactive_user_cannot_be_responsible(self, administrador, ejecutivo):
        ejecutivo.is_active = False
        ejecutivo.save()

        respuesta = api_como(administrador).post(
            responsable_url(nuevo_contrato()),
            {"ejecutivo": ejecutivo.pk},
        )

        assert respuesta.status_code == HTTPStatus.BAD_REQUEST

    def test_it_cannot_be_cleared(self, administrador, ejecutivo):
        contrato = nuevo_contrato(ejecutivo=ejecutivo)

        respuesta = api_como(administrador).post(
            responsable_url(contrato),
            {"ejecutivo": None},
            format="json",
        )

        assert respuesta.status_code == HTTPStatus.BAD_REQUEST

    @pytest.mark.parametrize(
        "estado",
        [Contrato.Estado.ANULADO, Contrato.Estado.TERMINADO],
    )
    def test_a_closed_contract_answers_409(self, administrador, ejecutivo, estado):
        contrato = nuevo_contrato()
        Contrato.objects.filter(pk=contrato.pk).update(estado=estado)

        respuesta = api_como(administrador).post(
            responsable_url(contrato),
            {"ejecutivo": ejecutivo.pk},
        )

        assert respuesta.status_code == HTTPStatus.CONFLICT
        assert respuesta.json()["codigo"] == "contrato_no_editable"

    def test_a_draft_can_have_one(self, administrador, ejecutivo):
        contrato = nuevo_contrato(borrador=True)

        respuesta = api_como(administrador).post(
            responsable_url(contrato),
            {"ejecutivo": ejecutivo.pk},
        )

        assert respuesta.status_code == HTTPStatus.OK

    def test_contracts_still_have_no_patch_or_delete(self, administrador):
        contrato = nuevo_contrato()
        detalle = reverse("api:contrato-detail", kwargs={"pk": contrato.pk})
        cliente = api_como(administrador)

        assert cliente.patch(detalle, {}).status_code == HTTPStatus.METHOD_NOT_ALLOWED
        # Refused by permission first: nobody holds delete_contrato.
        assert cliente.delete(detalle).status_code == HTTPStatus.FORBIDDEN
        assert Contrato.objects.filter(pk=contrato.pk).exists()


class TestEjecutivos:
    def test_it_lists_the_active_staff_who_handle_alerts(
        self,
        administrador,
        ejecutivo,
    ):
        UserFactory.create()
        inactivo = usuario_con_rol(seed.EJECUTIVO)
        inactivo.is_active = False
        inactivo.save()

        respuesta = api_como(administrador).get(EJECUTIVOS)

        assert respuesta.status_code == HTTPStatus.OK
        assert {fila["id"] for fila in respuesta.json()} == {
            administrador.pk,
            ejecutivo.pk,
        }
        assert {"id": ejecutivo.pk, "nombre": ejecutivo.name} in respuesta.json()

    def test_only_the_administrador_gets_the_list(self, ejecutivo):
        respuesta = api_como(ejecutivo).get(EJECUTIVOS)

        assert respuesta.status_code == HTTPStatus.FORBIDDEN


class TestPermisosDeLosRoles:
    def test_ejecutivo(self, ejecutivo):
        assert ejecutivo.has_perm("contratos.view_alertavencimiento")
        assert ejecutivo.has_perm("contratos.gestionar_alertavencimiento")
        assert not ejecutivo.has_perm("contratos.ver_todas_alertasvencimiento")
        assert not ejecutivo.has_perm("contratos.asignar_responsable_contrato")

    def test_administrador(self, administrador):
        for permiso in (
            "view_alertavencimiento",
            "gestionar_alertavencimiento",
            "ver_todas_alertasvencimiento",
            "asignar_responsable_contrato",
        ):
            assert administrador.has_perm(f"contratos.{permiso}")

    @pytest.mark.parametrize("rol", [seed.ADMINISTRADOR, seed.EJECUTIVO])
    def test_nobody_edits_an_alert_by_hand(self, rol):
        usuario = usuario_con_rol(rol)

        for permiso in (
            "add_alertavencimiento",
            "change_alertavencimiento",
            "delete_alertavencimiento",
        ):
            assert not usuario.has_perm(f"contratos.{permiso}")
