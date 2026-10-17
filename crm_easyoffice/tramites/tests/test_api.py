"""Cases API, portal and backoffice. Every name, RUT and email is synthetic."""

from __future__ import annotations

import importlib
from datetime import timedelta
from http import HTTPStatus

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from crm_easyoffice.clientes.tests.factories import CuentaClienteFactory
from crm_easyoffice.clientes.tests.factories import PersonaFactory
from crm_easyoffice.clientes.tests.factories import synthetic_rut
from crm_easyoffice.tramites.api.views import REPRESENTANTE_NO_DISPONIBLE
from crm_easyoffice.tramites.models import Tramite
from crm_easyoffice.tramites.services import documento_fallido
from crm_easyoffice.tramites.services import documento_listo
from crm_easyoffice.tramites.tests.factories import cuenta_empresa
from crm_easyoffice.tramites.tests.factories import payload_domicilio
from crm_easyoffice.tramites.tests.factories import preparar_domicilio
from crm_easyoffice.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

roles = importlib.import_module("crm_easyoffice.core.migrations.0002_seed_roles")

FORMULARIO = reverse("portal:tramite-formulario-domicilio")
CREAR = reverse("portal:tramite-crear-domicilio")
PORTAL = reverse("portal:tramite-list")
BACKOFFICE = reverse("api:tramite-list")


def portal(cuenta) -> APIClient:
    client = APIClient()
    client.force_authenticate(cuenta.user)
    return client


def staff(rol: str | None) -> APIClient:
    user = UserFactory.create()
    if rol:
        user.groups.add(Group.objects.get(name=rol))
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def sucursal():
    return preparar_domicilio("LF")


@pytest.fixture
def cuenta():
    return cuenta_empresa()


def crear(cuenta, sucursal, rut: str | None = None, **extra):
    payload = payload_domicilio(cuenta.cliente, sucursal, **extra)
    if rut:
        payload["representante"]["rut"] = rut
    return portal(cuenta).post(CREAR, payload, format="json")


class TestFormulario:
    def test_company_client_gets_choices_and_prefill(self, cuenta, sucursal):
        respuesta = portal(cuenta).get(FORMULARIO)

        assert respuesta.status_code == HTTPStatus.OK
        cuerpo = respuesta.json()
        assert cuerpo["disponible"] is True
        assert [s["codigo"] for s in cuerpo["sucursales"]] == ["LF"]
        assert cuerpo["sucursales"][0]["direccion"] == sucursal.direccion_completa
        planes = {p["codigo"]: p for p in cuerpo["planes"]}
        assert planes["anual"]["precio"] == "59990"
        assert planes["anual"]["precio_firma"] is None
        assert planes["semestral"]["precio_firma"] == "5000"
        assert cuerpo["datos"]["empresa"]["rut"] == cuenta.cliente.empresa.rut

    def test_requires_a_client_session(self, sucursal):
        assert APIClient().get(FORMULARIO).status_code == HTTPStatus.FORBIDDEN
        assert staff(roles.EJECUTIVO).get(FORMULARIO).status_code == (
            HTTPStatus.FORBIDDEN
        )

    def test_a_person_client_sees_why_not(self, sucursal):
        respuesta = portal(CuentaClienteFactory.create()).get(FORMULARIO)

        assert respuesta.json()["disponible"] is False
        assert respuesta.json()["datos"] is None


class TestCrear:
    def test_files_the_request(self, cuenta, sucursal):
        respuesta = crear(cuenta, sucursal)

        assert respuesta.status_code == HTTPStatus.CREATED
        cuerpo = respuesta.json()
        assert cuerpo["estado"] == "iniciado"
        assert cuerpo["contrato"]["folio"].startswith("LF-")
        assert cuerpo["contrato"]["sucursal"]["id"] == sucursal.pk
        assert cuerpo["contrato"]["precio"] == "59990"

    @pytest.mark.parametrize(
        ("campo", "valor", "error"),
        [
            ("movil_aviso", "12345678", "movil_aviso"),
            ("email_aviso", "no-es-correo", "email_aviso"),
            ("fecha_inicio", "2020-01-01", "fecha_inicio"),
        ],
    )
    def test_rejects_invalid_fields(self, cuenta, sucursal, campo, valor, error):
        respuesta = crear(cuenta, sucursal, **{campo: valor})

        assert respuesta.status_code == HTTPStatus.BAD_REQUEST
        assert error in respuesta.json()
        assert not Tramite.objects.exists()

    def test_rejects_an_invalid_rut(self, cuenta, sucursal):
        payload = payload_domicilio(cuenta.cliente, sucursal)
        payload["representante"]["rut"] = "12345678-0"

        respuesta = portal(cuenta).post(CREAR, payload, format="json")

        assert respuesta.status_code == HTTPStatus.BAD_REQUEST
        assert "rut" in respuesta.json()["representante"]

    def test_a_future_personeria_is_rejected(self, cuenta, sucursal):
        payload = payload_domicilio(cuenta.cliente, sucursal)
        manana = timezone.localdate() + timedelta(days=1)
        payload["personeria"]["fecha_instrumento"] = manana.isoformat()

        respuesta = portal(cuenta).post(CREAR, payload, format="json")

        assert "fecha_instrumento" in respuesta.json()["personeria"]

    def test_someone_elses_rut_gets_a_generic_answer(self, cuenta, sucursal):
        payload = payload_domicilio(cuenta.cliente, sucursal)
        payload["representante"]["rut"] = PersonaFactory.create().rut

        respuesta = portal(cuenta).post(CREAR, payload, format="json")

        assert respuesta.status_code == HTTPStatus.BAD_REQUEST
        assert respuesta.json() == {
            "representante": {
                "rut": [str(REPRESENTANTE_NO_DISPONIBLE)],
            },
        }

    def test_unavailable_online_is_a_conflict(self, sucursal):
        persona = CuentaClienteFactory.create()
        payload = payload_domicilio(cuenta_empresa().cliente, sucursal)

        respuesta = portal(persona).post(CREAR, payload, format="json")

        assert respuesta.status_code == HTTPStatus.CONFLICT
        assert respuesta.json()["codigo"] == "no_disponible"


class TestTramitePortal:
    def test_lists_and_shows_only_own_cases(self, cuenta, sucursal):
        propio = crear(cuenta, sucursal).json()
        otra = cuenta_empresa()
        ajeno = crear(otra, sucursal, rut=synthetic_rut(32_999_888)).json()

        lista = portal(cuenta).get(PORTAL).json()["results"]

        assert [t["id"] for t in lista] == [propio["id"]]
        detalle = reverse("portal:tramite-detail", args=[ajeno["id"]])
        assert portal(cuenta).get(detalle).status_code == HTTPStatus.NOT_FOUND

    def test_internal_notes_stay_out_of_the_portal(self, cuenta, sucursal):
        tramite = Tramite.objects.get(pk=crear(cuenta, sucursal).json()["id"])
        documento_fallido(tramite, "Falta el reverso de la cédula del autorizante.")

        cuerpo = portal(cuenta).get(reverse("portal:tramite-detail", args=[tramite.pk]))

        texto = cuerpo.content.decode()
        assert "reverso" not in texto
        assert cuerpo.json()["motivo"]["codigo"] == "falta_informacion"
        assert cuerpo.json()["accion_cliente"] is None

    def test_confirm_moves_to_payment(self, cuenta, sucursal):
        tramite = Tramite.objects.get(pk=crear(cuenta, sucursal).json()["id"])
        documento_listo(tramite)

        respuesta = portal(cuenta).post(
            reverse("portal:tramite-confirmar", args=[tramite.pk]),
        )

        assert respuesta.status_code == HTTPStatus.OK
        assert respuesta.json()["accion_cliente"] == "pagar"
        assert respuesta.json()["venta"]["total"] == "59990"

    def test_confirm_before_the_document_is_a_conflict(self, cuenta, sucursal):
        tramite_id = crear(cuenta, sucursal).json()["id"]

        respuesta = portal(cuenta).post(
            reverse("portal:tramite-confirmar", args=[tramite_id]),
        )

        assert respuesta.status_code == HTTPStatus.CONFLICT
        assert respuesta.json()["codigo"] == "transicion_invalida"

    def test_edit_regenerates(self, cuenta, sucursal):
        tramite = Tramite.objects.get(pk=crear(cuenta, sucursal).json()["id"])
        documento_listo(tramite)

        respuesta = portal(cuenta).put(
            reverse("portal:tramite-editar-domicilio", args=[tramite.pk]),
            payload_domicilio(cuenta.cliente, sucursal, plan="semestral"),
            format="json",
        )

        assert respuesta.status_code == HTTPStatus.OK
        assert respuesta.json()["estado"] == "iniciado"
        assert respuesta.json()["contrato"]["duracion_meses"] == 6  # noqa: PLR2004


class TestBackoffice:
    def test_staff_with_permission_see_every_case(self, cuenta, sucursal):
        tramite = Tramite.objects.get(pk=crear(cuenta, sucursal).json()["id"])
        documento_fallido(tramite, "Falta el reverso.")

        respuesta = staff(roles.EJECUTIVO).get(
            BACKOFFICE,
            {"motivo": "falta_informacion"},
        )

        assert respuesta.status_code == HTTPStatus.OK
        (fila,) = respuesta.json()["results"]
        assert fila["detalle_pendiente"] == "Falta el reverso."
        assert fila["cliente"]["rut"] == cuenta.cliente.empresa.rut

    def test_search_by_contract_folio(self, cuenta, sucursal):
        cuerpo = crear(cuenta, sucursal).json()

        respuesta = staff(roles.ADMINISTRADOR).get(
            BACKOFFICE,
            {"buscar": cuerpo["contrato"]["folio"]},
        )

        assert [t["id"] for t in respuesta.json()["results"]] == [cuerpo["id"]]

    def test_requires_permission(self, cuenta, sucursal):
        assert staff(None).get(BACKOFFICE).status_code == HTTPStatus.FORBIDDEN
        assert portal(cuenta).get(BACKOFFICE).status_code == HTTPStatus.FORBIDDEN

    def test_is_read_only(self, cuenta, sucursal):
        tramite_id = crear(cuenta, sucursal).json()["id"]

        respuesta = staff(roles.ADMINISTRADOR).delete(
            reverse("api:tramite-detail", args=[tramite_id]),
        )

        assert respuesta.status_code in {
            HTTPStatus.FORBIDDEN,
            HTTPStatus.METHOD_NOT_ALLOWED,
        }
        assert Tramite.objects.filter(pk=tramite_id).exists()
