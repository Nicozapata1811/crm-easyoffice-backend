"""Advanced signature through the provider (IN-01, RF-25, RF-39, RF-40).

The warehouse case, started in the backoffice, with its type switched to
``avanzada`` and the simulated provider standing in for the real one.
Synthetic data only.
"""

from __future__ import annotations

import importlib
import json
import time
from http import HTTPStatus

import pytest
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from crm_easyoffice.clientes.tests.factories import CuentaClienteFactory
from crm_easyoffice.configuracion.models import ConfigEmpresa
from crm_easyoffice.contratos.models import Contrato
from crm_easyoffice.documentos import firma
from crm_easyoffice.documentos.models import Documento
from crm_easyoffice.documentos.models import EventoFirma
from crm_easyoffice.documentos.models import Firmante
from crm_easyoffice.documentos.models import SolicitudFirma
from crm_easyoffice.documentos.tasks import sincronizar_solicitudes_abiertas
from crm_easyoffice.documentos.tests.factories import documento_generado
from crm_easyoffice.documentos.tests.test_api import a_firma as pagar_y_firmar
from crm_easyoffice.documentos.tests.test_api import caso  # noqa: F401 - fixture
from crm_easyoffice.integrations.signature.base import SignatureEventType
from crm_easyoffice.integrations.signature.http import firma_webhook
from crm_easyoffice.integrations.signature.simulated import SimulatedSignatureProvider
from crm_easyoffice.tramites.models import TipoTramite
from crm_easyoffice.tramites.models import Tramite
from crm_easyoffice.tramites.tests.factories import TIPO_BODEGA
from crm_easyoffice.tramites.tests.factories import cliente_empresa
from crm_easyoffice.tramites.tests.factories import payload_bodega
from crm_easyoffice.tramites.tests.factories import preparar_bodega_caso
from crm_easyoffice.tramites.tests.factories import tramite_con_historia
from crm_easyoffice.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

roles = importlib.import_module("crm_easyoffice.core.migrations.0002_seed_roles")

TRAMITES = reverse("api:tramite-list")
ORDEN = ["cliente_representante", "representante_emisor", "autorizante"]


def staff(rol: str = roles.EJECUTIVO) -> APIClient:
    user = UserFactory.create()
    user.groups.add(Group.objects.get(name=rol))
    client = APIClient()
    client.force_authenticate(user)
    return client


def documentos_de(client, tramite_id: int) -> list[dict]:
    return client.get(
        reverse("documentos:tramite-documentos", kwargs={"tramite_id": tramite_id}),
    ).json()


def ruta(nombre: str, tramite_id: int, documento_id: int) -> str:
    return reverse(
        f"documentos:tramite-documento-{nombre}",
        kwargs={"tramite_id": tramite_id, "pk": documento_id},
    )


@pytest.fixture
def proveedor(monkeypatch) -> SimulatedSignatureProvider:
    """One simulated provider for the whole test, as a real one would be."""
    simulado = SimulatedSignatureProvider(auto_sign=False)
    for modulo in (
        "crm_easyoffice.documentos.firma",
        "crm_easyoffice.documentos.api.webhook_views",
    ):
        monkeypatch.setattr(f"{modulo}.get_signature_provider", lambda: simulado)
    return simulado


def nivel(nivel_firma: str, firmantes: list[str] | None = None) -> None:
    tipo = TipoTramite.objects.get(codigo=TIPO_BODEGA)
    tipo.configuracion["firma"] = {"nivel": nivel_firma}
    if firmantes:
        tipo.configuracion["firma"]["firmantes"] = firmantes
    tipo.save()


@pytest.fixture
def avanzada():
    nivel("avanzada", ORDEN)


@pytest.fixture
def client():
    return staff()


def a_firma(client, django_capture_on_commit_callbacks) -> Tramite:
    """Start a warehouse case in the backoffice and confirm its draft."""
    sucursal, bodega = preparar_bodega_caso("LF")
    cliente = cliente_empresa()
    with django_capture_on_commit_callbacks(execute=True):
        creado = client.post(
            TRAMITES,
            payload_bodega(cliente, sucursal, bodega),
            format="json",
        )
    assert creado.status_code == HTTPStatus.CREATED, creado.json()
    tramite_id = creado.json()["id"]
    with django_capture_on_commit_callbacks(execute=True):
        confirmado = client.post(
            reverse("api:tramite-confirmar", kwargs={"pk": tramite_id}),
        )
    assert confirmado.json()["motivo"]["codigo"] == "firma"
    return Tramite.objects.get(pk=tramite_id)


def webhook(client_publico, proveedor, solicitud, tipo, capture):
    cuerpo = proveedor.event(solicitud.id_externo, tipo)
    with capture(execute=True):
        return client_publico.post(
            reverse("firma:webhook", args=["simulated"]),
            data=cuerpo,
            content_type="application/json",
        )


def test_assisted_types_are_untouched(
    client,
    proveedor,
    django_capture_on_commit_callbacks,
):
    tramite = a_firma(client, django_capture_on_commit_callbacks)

    assert not SolicitudFirma.objects.exists()
    (documento,) = documentos_de(client, tramite.pk)
    assert [f["rol"] for f in documento["firmantes"]] == [
        "cliente_representante",
        "autorizante",
    ]
    assert documento["firma"] == {
        "nivel": "asistida",
        "ambiente_pruebas": False,
        "solicitud": None,
    }


def test_the_document_goes_to_the_provider_with_its_signers_in_order(
    client,
    proveedor,
    avanzada,
    django_capture_on_commit_callbacks,
):
    tramite = a_firma(client, django_capture_on_commit_callbacks)

    solicitud = SolicitudFirma.objects.get()
    assert solicitud.estado == SolicitudFirma.Estado.ENVIADA
    assert solicitud.id_externo.startswith("sim-")
    assert solicitud.expira_en is not None
    documento = solicitud.documento
    firmantes = list(documento.firmantes.order_by("orden"))
    assert [f.rol for f in firmantes] == ORDEN
    assert firmantes[1].persona == ConfigEmpresa.objects.get().representante
    assert all(f.id_externo for f in firmantes)
    assert all(f.estado == Firmante.Estado.PENDIENTE for f in firmantes)
    resultado = proveedor.get_status(solicitud.id_externo)
    assert resultado.original_sha256 == documento.sha256_pdf
    assert tramite.estado == "pendiente"


def test_each_signer_and_the_completion_arrive_by_webhook(
    client,
    proveedor,
    avanzada,
    django_capture_on_commit_callbacks,
):
    tramite = a_firma(client, django_capture_on_commit_callbacks)
    solicitud = SolicitudFirma.objects.get()
    publico = APIClient()

    for _ in range(len(ORDEN) - 1):
        proveedor.sign_next(solicitud.id_externo)
        respuesta = webhook(
            publico,
            proveedor,
            solicitud,
            SignatureEventType.SIGNER_SIGNED,
            django_capture_on_commit_callbacks,
        )
        assert respuesta.status_code == HTTPStatus.OK
    firmados = solicitud.documento.firmantes.filter(firmado_en__isnull=False)
    assert firmados.count() == len(ORDEN) - 1
    assert Tramite.objects.get(pk=tramite.pk).estado == "pendiente"

    proveedor.sign_next(solicitud.id_externo)
    webhook(
        publico,
        proveedor,
        solicitud,
        SignatureEventType.COMPLETED,
        django_capture_on_commit_callbacks,
    )

    solicitud.refresh_from_db()
    assert solicitud.estado == SolicitudFirma.Estado.COMPLETADA
    documento = Documento.objects.get(pk=solicitud.documento_id)
    assert documento.estado == Documento.Estado.FIRMADO
    firmado = proveedor.download_signed(solicitud.id_externo)
    assert documento.archivo_firmado.open("rb").read() == firmado
    assert (
        documento.sha256_firmado
        == proveedor.get_status(solicitud.id_externo).signed_hash
    )
    assert documento.firmado_por is None
    assert all(f.estado == Firmante.Estado.FIRMADO for f in documento.firmantes.all())
    tramite.refresh_from_db()
    assert tramite.estado == "completado"
    assert tramite.contrato.estado == Contrato.Estado.VIGENTE
    assert EventoFirma.objects.filter(
        resultado=EventoFirma.Resultado.RECIBIDO,
    ).count() == len(
        ORDEN,
    )


def test_a_repeated_webhook_is_recorded_once(
    client,
    proveedor,
    avanzada,
    django_capture_on_commit_callbacks,
):
    a_firma(client, django_capture_on_commit_callbacks)
    solicitud = SolicitudFirma.objects.get()
    cuerpo = proveedor.event(solicitud.id_externo, SignatureEventType.SIGNER_SIGNED)
    publico = APIClient()
    url = reverse("firma:webhook", args=["simulated"])

    for _ in range(2):
        with django_capture_on_commit_callbacks(execute=True):
            publico.post(url, data=cuerpo, content_type="application/json")

    assert EventoFirma.objects.count() == 1


def test_a_signed_file_that_does_not_keep_the_document_sent_is_refused(
    client,
    proveedor,
    avanzada,
    django_capture_on_commit_callbacks,
    monkeypatch,
):
    tramite = a_firma(client, django_capture_on_commit_callbacks)
    solicitud = SolicitudFirma.objects.get()
    for _ in ORDEN:
        proveedor.sign_next(solicitud.id_externo)
    monkeypatch.setattr(
        proveedor,
        "download_signed",
        lambda _: b"%PDF-1.7 otro documento",
    )

    firma.sincronizar(solicitud.pk)

    solicitud.refresh_from_db()
    assert solicitud.estado == SolicitudFirma.Estado.ERROR
    assert "no conserva el documento" in solicitud.detalle_error
    tramite.refresh_from_db()
    assert tramite.estado == "pendiente"
    assert not Documento.objects.get(pk=solicitud.documento_id).archivo_firmado


def test_a_different_original_hash_is_refused(
    client,
    proveedor,
    avanzada,
    django_capture_on_commit_callbacks,
):
    a_firma(client, django_capture_on_commit_callbacks)
    solicitud = SolicitudFirma.objects.get()
    for _ in ORDEN:
        proveedor.sign_next(solicitud.id_externo)
    proveedor._update(solicitud.id_externo, original_sha256="0" * 64)  # noqa: SLF001

    firma.sincronizar(solicitud.pk)

    solicitud.refresh_from_db()
    assert solicitud.estado == SolicitudFirma.Estado.ERROR
    assert "mismo documento" in solicitud.detalle_error


def test_a_decline_sends_the_case_back_with_the_reason(
    client,
    proveedor,
    avanzada,
    django_capture_on_commit_callbacks,
):
    tramite = a_firma(client, django_capture_on_commit_callbacks)
    solicitud = SolicitudFirma.objects.get()
    proveedor.decline(solicitud.id_externo, "La dirección está mal.")

    webhook(
        APIClient(),
        proveedor,
        solicitud,
        SignatureEventType.SIGNER_DECLINED,
        django_capture_on_commit_callbacks,
    )

    solicitud.refresh_from_db()
    assert solicitud.estado == SolicitudFirma.Estado.RECHAZADA
    rechazo = solicitud.documento.firmantes.get(orden=1)
    assert rechazo.estado == Firmante.Estado.RECHAZADO
    assert rechazo.motivo_rechazo == "La dirección está mal."
    tramite.refresh_from_db()
    assert (tramite.estado, tramite.motivo.codigo) == ("pendiente", "falta_informacion")
    assert "La dirección está mal." in tramite.detalle_pendiente


def test_an_expired_request_sends_the_case_back(
    client,
    proveedor,
    avanzada,
    django_capture_on_commit_callbacks,
):
    tramite = a_firma(client, django_capture_on_commit_callbacks)
    solicitud = SolicitudFirma.objects.get()
    proveedor.expire(solicitud.id_externo)

    webhook(
        APIClient(),
        proveedor,
        solicitud,
        SignatureEventType.EXPIRED,
        django_capture_on_commit_callbacks,
    )

    assert SolicitudFirma.objects.get().estado == SolicitudFirma.Estado.EXPIRADA
    tramite.refresh_from_db()
    assert tramite.motivo.codigo == "falta_informacion"
    assert tramite.detalle_pendiente == firma.EXPIRADA


def test_the_periodic_sync_completes_a_case_whose_webhooks_were_lost(
    client,
    proveedor,
    avanzada,
    django_capture_on_commit_callbacks,
):
    tramite = a_firma(client, django_capture_on_commit_callbacks)
    solicitud = SolicitudFirma.objects.get()
    for _ in ORDEN:
        proveedor.sign_next(solicitud.id_externo)

    assert sincronizar_solicitudes_abiertas() == 1

    tramite.refresh_from_db()
    assert tramite.estado == "completado"
    assert sincronizar_solicitudes_abiertas() == 0


def test_the_backoffice_sees_each_signer_and_the_request(
    client,
    proveedor,
    avanzada,
    django_capture_on_commit_callbacks,
):
    tramite = a_firma(client, django_capture_on_commit_callbacks)
    solicitud = SolicitudFirma.objects.get()
    proveedor.sign_next(solicitud.id_externo)
    firma.sincronizar(solicitud.pk)

    (documento,) = documentos_de(client, tramite.pk)

    assert documento["firma"]["nivel"] == "avanzada"
    assert documento["firma"]["solicitud"]["id_externo"] == solicitud.id_externo
    assert documento["firma"]["solicitud"]["estado"] == "enviada"
    assert [f["estado"] for f in documento["firmantes"]] == [
        "firmado",
        "pendiente",
        "pendiente",
    ]
    assert documento["firmantes"][0]["firmado_en"]


def test_the_portal_sees_only_names_and_states(
    proveedor,
    avanzada,
    django_capture_on_commit_callbacks,
):
    tramite = a_firma(staff(), django_capture_on_commit_callbacks)
    cliente = APIClient()
    cliente.force_authenticate(
        CuentaClienteFactory.create(cliente=tramite.cliente).user,
    )

    (documento,) = cliente.get(
        reverse("portal:tramite-documentos", kwargs={"tramite_id": tramite.pk}),
    ).json()

    assert set(documento["firmantes"][0]) == {
        "orden",
        "rol",
        "nombre",
        "estado",
        "firmado_en",
    }
    assert set(documento["firma"]) == {"nivel", "ambiente_pruebas"}


def test_the_assisted_upload_is_refused_for_advanced_types(
    client,
    proveedor,
    avanzada,
    django_capture_on_commit_callbacks,
):
    tramite = a_firma(client, django_capture_on_commit_callbacks)
    documento = tramite.documentos.get()

    respuesta = client.post(
        ruta("subir-firmado", tramite.pk, documento.pk),
        {"archivo": SimpleUploadedFile("f.pdf", b"%PDF-1.7\n%%EOF\n")},
        format="multipart",
    )

    assert respuesta.status_code == HTTPStatus.CONFLICT
    assert respuesta.json()["codigo"] == "firma_avanzada"


def test_resend_and_cancel(
    client,
    proveedor,
    avanzada,
    django_capture_on_commit_callbacks,
):
    tramite = a_firma(client, django_capture_on_commit_callbacks)
    solicitud = SolicitudFirma.objects.get()
    documento = solicitud.documento
    primero = documento.firmantes.get(orden=1)

    with django_capture_on_commit_callbacks(execute=True):
        reenviado = client.post(
            ruta("firma-reenviar", tramite.pk, documento.pk),
            {"firmante": primero.pk},
            format="json",
        )
    assert reenviado.status_code == HTTPStatus.ACCEPTED
    assert proveedor.resent == [(solicitud.id_externo, primero.id_externo)]

    with django_capture_on_commit_callbacks(execute=True):
        cancelado = client.post(ruta("firma-cancelar", tramite.pk, documento.pk))
    assert cancelado.status_code == HTTPStatus.ACCEPTED
    solicitud.refresh_from_db()
    assert solicitud.estado == SolicitudFirma.Estado.CANCELADA
    tramite.refresh_from_db()
    assert tramite.detalle_pendiente == firma.CANCELADA_POR_EJECUTIVO

    otra_vez = client.post(ruta("firma-cancelar", tramite.pk, documento.pk))
    assert otra_vez.status_code == HTTPStatus.CONFLICT


def test_managing_the_signature_needs_the_permission(
    proveedor,
    avanzada,
    django_capture_on_commit_callbacks,
):
    tramite = a_firma(staff(), django_capture_on_commit_callbacks)
    documento = tramite.documentos.get()
    sin_permiso = APIClient()
    sin_permiso.force_authenticate(UserFactory.create())

    respuesta = sin_permiso.post(ruta("firma-cancelar", tramite.pk, documento.pk))

    assert respuesta.status_code == HTTPStatus.FORBIDDEN


def test_a_failed_request_can_be_retried(
    client,
    proveedor,
    avanzada,
    django_capture_on_commit_callbacks,
):
    tramite = a_firma(client, django_capture_on_commit_callbacks)
    solicitud = SolicitudFirma.objects.get()
    SolicitudFirma.objects.filter(pk=solicitud.pk).update(
        estado=SolicitudFirma.Estado.ERROR,
    )

    with django_capture_on_commit_callbacks(execute=True):
        respuesta = client.post(
            ruta("firma-reintentar", tramite.pk, solicitud.documento_id),
        )

    assert respuesta.status_code == HTTPStatus.ACCEPTED
    assert (
        SolicitudFirma.objects.filter(estado=SolicitudFirma.Estado.ENVIADA).count() == 1
    )


def test_a_signer_without_email_is_reported_to_the_executive(
    client,
    proveedor,
    django_capture_on_commit_callbacks,
):
    nivel("avanzada", ORDEN)
    sucursal, bodega = preparar_bodega_caso("LF")
    representante = ConfigEmpresa.objects.get().representante
    representante.email = ""
    representante.save()
    with django_capture_on_commit_callbacks(execute=True):
        creado = client.post(
            TRAMITES,
            payload_bodega(cliente_empresa(), sucursal, bodega),
            format="json",
        )
    with django_capture_on_commit_callbacks(execute=True):
        client.post(
            reverse("api:tramite-confirmar", kwargs={"pk": creado.json()["id"]}),
        )

    solicitud = SolicitudFirma.objects.get()
    assert solicitud.estado == SolicitudFirma.Estado.ERROR
    assert representante.nombre_completo in solicitud.detalle_error


def test_a_portal_domicile_case_goes_to_the_provider_once_paid(
    caso,  # noqa: F811
    proveedor,
    django_capture_on_commit_callbacks,
):
    """Not only the warehouse or the backoffice: any type whose level is avanzada."""
    tipo = TipoTramite.objects.get(codigo="domicilio-tributario")
    tipo.configuracion["firma"] = {"nivel": "avanzada", "firmantes": ORDEN}
    tipo.save()
    _, tramite, _ = caso
    # The document generated before the switch keeps its two signers.
    assert not SolicitudFirma.objects.exists()

    tramite = pagar_y_firmar(tramite, django_capture_on_commit_callbacks)

    solicitud = SolicitudFirma.objects.get()
    assert tramite.canal == Tramite.Canal.PORTAL
    assert solicitud.estado == SolicitudFirma.Estado.ENVIADA
    for _ in solicitud.documento.firmantes.all():
        proveedor.sign_next(solicitud.id_externo)
    firma.sincronizar(solicitud.pk)
    tramite.refresh_from_db()
    assert tramite.estado == "completado"
    assert tramite.contrato.estado == Contrato.Estado.VIGENTE


@pytest.fixture
def http(settings, monkeypatch):
    """The HTTP adapter, for the webhook's own checks; processing is stubbed."""
    settings.SIGNATURE_PROVIDER = "http"
    settings.SIGNATURE_API_BASE_URL = "http://firma-sandbox:8100/api/v1/"
    settings.SIGNATURE_API_KEY = "clave-de-prueba"
    settings.SIGNATURE_WEBHOOK_SECRET = "secreto-de-prueba"  # noqa: S105
    procesados: list[int] = []
    monkeypatch.setattr(
        "crm_easyoffice.documentos.api.webhook_views.procesar_evento_firma.delay",
        procesados.append,
    )
    return procesados


def _evento_http(id_evento="ev-1", marca=None, secreto="secreto-de-prueba"):
    cuerpo = json.dumps(
        {
            "id_evento": id_evento,
            "tipo": "firmante.firmo",
            "solicitud": {"id": "remota-1", "estado": "pendiente", "firmantes": []},
        },
    ).encode()
    marca = str(int(time.time()) if marca is None else marca)
    return cuerpo, {
        "HTTP_X_PSC_EVENTO": id_evento,
        "HTTP_X_PSC_TIMESTAMP": marca,
        "HTTP_X_PSC_FIRMA": firma_webhook(secreto, marca, cuerpo),
    }


def _post(cuerpo, encabezados, capture):
    with capture(execute=True):
        return APIClient().post(
            reverse("firma:webhook", args=["http"]),
            data=cuerpo,
            content_type="application/json",
            **encabezados,
        )


def test_the_webhook_checks_hmac_and_timestamp(
    http,
    django_capture_on_commit_callbacks,
):
    falsa, encabezados = _evento_http(secreto="otro")
    assert (
        _post(falsa, encabezados, django_capture_on_commit_callbacks).status_code
        == HTTPStatus.UNAUTHORIZED
    )
    vieja, encabezados = _evento_http(marca=int(time.time()) - 3600)
    assert (
        _post(vieja, encabezados, django_capture_on_commit_callbacks).status_code
        == HTTPStatus.UNAUTHORIZED
    )
    assert set(EventoFirma.objects.values_list("resultado", flat=True)) == {
        "firma_invalida",
    }


def test_the_webhook_deduplicates_by_event_id_and_processes_in_the_background(
    http,
    django_capture_on_commit_callbacks,
):
    tramite = tramite_con_historia((timezone.now(), "pendiente", "firma"))
    SolicitudFirma.objects.create(
        documento=documento_generado(tramite, 1, timezone.now()),
        proveedor="http",
        id_externo="remota-1",
        estado=SolicitudFirma.Estado.ENVIADA,
    )

    cuerpo, encabezados = _evento_http()
    primero = _post(cuerpo, encabezados, django_capture_on_commit_callbacks)
    cuerpo, encabezados = _evento_http()
    repetido = _post(cuerpo, encabezados, django_capture_on_commit_callbacks)

    assert primero.status_code == HTTPStatus.OK
    assert repetido.json() == {"status": "duplicado"}
    (evento,) = EventoFirma.objects.all()
    assert evento.resultado == EventoFirma.Resultado.RECIBIDO
    assert http == [evento.pk]


def test_the_webhook_of_another_provider_is_not_found(http):
    assert (
        APIClient()
        .post(
            reverse("firma:webhook", args=["otro"]),
            data=b"{}",
            content_type="application/json",
        )
        .status_code
        == HTTPStatus.NOT_FOUND
    )
