"""The warehouse case through the backoffice API, end to end. Synthetic data."""

from __future__ import annotations

import importlib
from http import HTTPStatus

import pytest
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APIClient

from crm_easyoffice.clientes.tests.factories import CuentaClienteFactory
from crm_easyoffice.contratos.models import Contrato
from crm_easyoffice.tramites.models import Tramite
from crm_easyoffice.tramites.tests.factories import cliente_empresa
from crm_easyoffice.tramites.tests.factories import payload_bodega
from crm_easyoffice.tramites.tests.factories import preparar_bodega_caso
from crm_easyoffice.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

roles = importlib.import_module("crm_easyoffice.core.migrations.0002_seed_roles")

TRAMITES = reverse("api:tramite-list")
TIPOS = reverse("api:tramite-tipos")
FORMULARIO = reverse("api:tramite-formulario")
PDF_FIRMADO = b"%PDF-1.7\n% firmado sintetico\n%%EOF\n"


def staff(rol: str | None) -> APIClient:
    user = UserFactory.create()
    if rol:
        user.groups.add(Group.objects.get(name=rol))
    client = APIClient()
    client.force_authenticate(user)
    return client


def accion(tramite_id: int, nombre: str) -> str:
    return reverse(f"api:tramite-{nombre}", kwargs={"pk": tramite_id})


@pytest.fixture
def inmuebles():
    return preparar_bodega_caso("LF")


@pytest.fixture
def cliente():
    return cliente_empresa()


def iniciar(client, cliente, inmuebles, django_capture_on_commit_callbacks, **extra):
    sucursal, bodega = inmuebles
    with django_capture_on_commit_callbacks(execute=True):
        return client.post(
            TRAMITES,
            payload_bodega(cliente, sucursal, bodega, **extra),
            format="json",
        )


@pytest.mark.parametrize("rol", [roles.EJECUTIVO, roles.ADMINISTRADOR])
def test_an_executive_runs_the_case_from_start_to_signature(
    rol,
    cliente,
    inmuebles,
    django_capture_on_commit_callbacks,
):
    client = staff(rol)

    creado = iniciar(client, cliente, inmuebles, django_capture_on_commit_callbacks)
    assert creado.status_code == HTTPStatus.CREATED, creado.json()
    cuerpo = creado.json()
    assert (cuerpo["tipo_codigo"], cuerpo["canal"]) == ("bodega", "backoffice")
    assert cuerpo["contrato"]["folio"].startswith("LF-")
    assert [s["inmueble"]["tipo"] for s in cuerpo["contrato"]["servicios"]] == [
        "oficina",
        "bodega",
    ]
    tramite_id = cuerpo["id"]

    detalle = client.get(accion(tramite_id, "detail")).json()
    assert (detalle["estado"], detalle["motivo"]["codigo"]) == (
        "pendiente",
        "revision_borrador",
    )
    assert detalle["editable"] is True
    documentos = client.get(
        reverse("documentos:tramite-documentos", kwargs={"tramite_id": tramite_id}),
    ).json()
    (documento,) = documentos
    assert documento["plantilla"].startswith("PLT-02")
    pdf = client.get(
        reverse(
            "documentos:tramite-documento-archivo",
            kwargs={"tramite_id": tramite_id, "pk": documento["id"], "tipo": "pdf"},
        ),
    )
    assert pdf.status_code == HTTPStatus.OK

    confirmado = client.post(accion(tramite_id, "confirmar"))
    assert confirmado.json()["motivo"]["codigo"] == "firma"
    assert confirmado.json()["venta"] is None

    subido = client.post(
        reverse(
            "documentos:tramite-documento-subir-firmado",
            kwargs={"tramite_id": tramite_id, "pk": documento["id"]},
        ),
        {"archivo": SimpleUploadedFile("firmado.pdf", PDF_FIRMADO)},
        format="multipart",
    )
    assert subido.status_code == HTTPStatus.OK, subido.json()
    tramite = Tramite.objects.get(pk=tramite_id)
    assert tramite.estado == "completado"
    assert tramite.contrato.estado == Contrato.Estado.VIGENTE


def test_the_executive_edits_the_draft(
    cliente,
    inmuebles,
    django_capture_on_commit_callbacks,
):
    client = staff(roles.EJECUTIVO)
    tramite_id = iniciar(
        client,
        cliente,
        inmuebles,
        django_capture_on_commit_callbacks,
    ).json()["id"]
    sucursal, bodega = inmuebles
    cambios = payload_bodega(cliente, sucursal, bodega, duracion_meses=6)
    del cambios["tipo"], cambios["cliente"]

    with django_capture_on_commit_callbacks(execute=True):
        respuesta = client.put(accion(tramite_id, "detail"), cambios, format="json")

    assert respuesta.status_code == HTTPStatus.OK, respuesta.json()
    assert respuesta.json()["contrato"]["duracion_meses"] == 6  # noqa: PLR2004
    assert Tramite.objects.get(pk=tramite_id).documentos.count() == 2  # noqa: PLR2004


def test_the_form_lists_the_choices(cliente, inmuebles):
    _, bodega = inmuebles

    respuesta = staff(roles.EJECUTIVO).get(
        FORMULARIO,
        {"tipo": "bodega", "cliente": cliente.pk},
    )

    assert respuesta.status_code == HTTPStatus.OK
    cuerpo = respuesta.json()
    assert cuerpo["disponible"] is True
    assert [i["id"] for i in cuerpo["inmuebles"]["bodega"]] == [bodega.pk]
    assert [i["codigo"] for i in cuerpo["inmuebles"]["sucursal"]] == ["LF"]
    lineas = {linea["servicio"]: linea for linea in cuerpo["lineas"]}
    assert lineas["bodega"]["precio_base"] is None
    assert lineas["domicilio-tributario"]["precio_base"] == "59990"
    assert cuerpo["datos"]["empresa"]["rut"] == cliente.empresa.rut


def test_the_startable_types_are_listed():
    respuesta = staff(roles.EJECUTIVO).get(TIPOS)

    assert respuesta.json() == [{"codigo": "bodega", "nombre": "Bodega virtual"}]


def test_unknown_type_or_client_is_a_field_error(inmuebles):
    respuesta = staff(roles.EJECUTIVO).get(FORMULARIO, {"tipo": "x", "cliente": "0"})

    assert respuesta.status_code == HTTPStatus.BAD_REQUEST
    assert set(respuesta.json()) == {"tipo", "cliente"}


def test_a_portal_type_cannot_be_started_here(cliente, inmuebles):
    sucursal, bodega = inmuebles
    payload = payload_bodega(cliente, sucursal, bodega, tipo="domicilio-tributario")

    respuesta = staff(roles.EJECUTIVO).post(TRAMITES, payload, format="json")

    assert respuesta.status_code == HTTPStatus.CONFLICT
    assert respuesta.json()["problemas"]


@pytest.mark.parametrize("nombre", ["create", "formulario", "confirmar", "editar"])
def test_staff_without_the_permission_cannot_act(
    nombre,
    cliente,
    inmuebles,
    django_capture_on_commit_callbacks,
):
    tramite_id = iniciar(
        staff(roles.EJECUTIVO),
        cliente,
        inmuebles,
        django_capture_on_commit_callbacks,
    ).json()["id"]
    sucursal, bodega = inmuebles
    payload = payload_bodega(cliente, sucursal, bodega)
    for client in (staff(None), _portal(cliente)):
        respuesta = {
            "create": lambda c: c.post(TRAMITES, payload, format="json"),
            "formulario": lambda c: c.get(
                FORMULARIO,
                {"tipo": "bodega", "cliente": cliente.pk},
            ),
            "confirmar": lambda c: c.post(accion(tramite_id, "confirmar")),
            "editar": lambda c: c.put(
                accion(tramite_id, "detail"),
                payload,
                format="json",
            ),
        }[nombre](client)
        assert respuesta.status_code == HTTPStatus.FORBIDDEN


def _portal(cliente) -> APIClient:
    cuenta = CuentaClienteFactory.create(cliente=cliente)
    client = APIClient()
    client.force_authenticate(cuenta.user)
    return client


def test_the_client_follows_a_backoffice_case_read_only(
    cliente,
    inmuebles,
    django_capture_on_commit_callbacks,
):
    tramite_id = iniciar(
        staff(roles.EJECUTIVO),
        cliente,
        inmuebles,
        django_capture_on_commit_callbacks,
    ).json()["id"]
    client = _portal(cliente)

    visto = client.get(reverse("portal:tramite-detail", kwargs={"pk": tramite_id}))
    confirmar = client.post(
        reverse("portal:tramite-confirmar", kwargs={"pk": tramite_id}),
    )

    assert visto.status_code == HTTPStatus.OK
    assert (visto.json()["editable"], visto.json()["accion_cliente"]) == (False, None)
    assert confirmar.status_code == HTTPStatus.CONFLICT
    assert confirmar.json()["codigo"] == "transicion_invalida"
