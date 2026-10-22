"""Document downloads and the signed upload. Every value here is synthetic."""

from __future__ import annotations

import importlib
from datetime import timedelta
from http import HTTPStatus

import pytest
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from crm_easyoffice.contratos.models import Contrato
from crm_easyoffice.core.models import RegistroAuditoria
from crm_easyoffice.documentos.models import Documento
from crm_easyoffice.integrations.payment.base import PaymentResult
from crm_easyoffice.integrations.payment.base import PaymentStatus
from crm_easyoffice.tramites.services import confirmar_borrador
from crm_easyoffice.tramites.services import iniciar_domicilio
from crm_easyoffice.tramites.services import situacion
from crm_easyoffice.tramites.tests.factories import cuenta_empresa
from crm_easyoffice.tramites.tests.factories import datos_domicilio
from crm_easyoffice.tramites.tests.factories import preparar_domicilio
from crm_easyoffice.users.tests.factories import UserFactory
from crm_easyoffice.ventas.models import OrdenPago
from crm_easyoffice.ventas.services import aplicar_resultado

pytestmark = pytest.mark.django_db

roles = importlib.import_module("crm_easyoffice.core.migrations.0002_seed_roles")

PDF_FIRMADO = b"%PDF-1.7\n% firmado sintetico\n%%EOF\n"


def staff(rol: str | None) -> APIClient:
    user = UserFactory.create()
    if rol:
        user.groups.add(Group.objects.get(name=rol))
    client = APIClient()
    client.force_authenticate(user)
    return client


def portal(cuenta) -> APIClient:
    client = APIClient()
    client.force_authenticate(cuenta.user)
    return client


@pytest.fixture
def caso(django_capture_on_commit_callbacks):
    """A case whose document was generated: (cuenta, tramite, documento)."""
    sucursal = preparar_domicilio("LF")
    cuenta = cuenta_empresa()
    with django_capture_on_commit_callbacks(execute=True):
        tramite = iniciar_domicilio(
            cuenta.cliente,
            datos_domicilio(cuenta.cliente, sucursal),
        )
    tramite.refresh_from_db()
    return cuenta, tramite, tramite.documentos.get()


def a_firma(tramite, django_capture_on_commit_callbacks):
    tramite = confirmar_borrador(tramite)
    venta = tramite.venta
    orden = OrdenPago.objects.create(
        venta=venta,
        proveedor="simulated",
        monto=venta.total,
    )
    with django_capture_on_commit_callbacks(execute=True):
        aplicar_resultado(
            orden.pk,
            PaymentResult(
                external_id="",
                reference=str(orden.referencia),
                status=PaymentStatus.PAID,
                amount=venta.total,
            ),
            origen="test",
        )
    tramite.refresh_from_db()
    return tramite


def url_archivo(nombre: str, tramite, documento, tipo: str) -> str:
    return reverse(nombre, args=[tramite.pk, documento.pk, tipo])


def subir(tramite, documento, contenido=PDF_FIRMADO, nombre="firmado.pdf", rol=None):
    return staff(rol or roles.EJECUTIVO).post(
        reverse(
            "documentos:tramite-documento-subir-firmado",
            args=[tramite.pk, documento.pk],
        ),
        {"archivo": SimpleUploadedFile(nombre, contenido)},
        format="multipart",
    )


class TestPortal:
    def test_lists_the_versions_of_an_own_case(self, caso):
        cuenta, tramite, documento = caso

        respuesta = portal(cuenta).get(
            reverse("portal:tramite-documentos", args=[tramite.pk]),
        )

        assert respuesta.status_code == HTTPStatus.OK
        (fila,) = respuesta.json()
        assert fila["version"] == 1
        assert fila["sha256_pdf"] == documento.sha256_pdf
        assert [f["rol"] for f in fila["firmantes"]] == [
            "cliente_representante",
            "autorizante",
        ]
        assert "archivo" not in str(fila)

    def test_the_pdf_is_shown_inline_and_never_cached(self, caso):
        cuenta, tramite, documento = caso

        respuesta = portal(cuenta).get(
            url_archivo("portal:tramite-documento-archivo", tramite, documento, "pdf"),
        )

        assert respuesta.status_code == HTTPStatus.OK
        assert respuesta["Content-Type"] == "application/pdf"
        assert respuesta["Cache-Control"] == "no-store, private"
        assert "inline" in respuesta["Content-Disposition"]
        assert b"".join(respuesta.streaming_content).startswith(b"%PDF-")

    def test_the_word_file_is_an_attachment(self, caso):
        cuenta, tramite, documento = caso

        respuesta = portal(cuenta).get(
            url_archivo("portal:tramite-documento-archivo", tramite, documento, "docx"),
        )

        assert "attachment" in respuesta["Content-Disposition"]
        assert tramite.contrato.folio in respuesta["Content-Disposition"]

    def test_another_clients_documents_are_not_found(self, caso):
        _, tramite, documento = caso
        otra = cuenta_empresa()

        lista = portal(otra).get(
            reverse("portal:tramite-documentos", args=[tramite.pk]),
        )
        archivo = portal(otra).get(
            url_archivo("portal:tramite-documento-archivo", tramite, documento, "pdf"),
        )

        assert lista.status_code == HTTPStatus.NOT_FOUND
        assert archivo.status_code == HTTPStatus.NOT_FOUND

    def test_no_signed_file_before_signing(self, caso):
        cuenta, tramite, documento = caso

        respuesta = portal(cuenta).get(
            url_archivo(
                "portal:tramite-documento-archivo",
                tramite,
                documento,
                "firmado",
            ),
        )

        assert respuesta.status_code == HTTPStatus.NOT_FOUND


class TestBackoffice:
    def test_staff_with_permission_download(self, caso):
        _, tramite, documento = caso

        respuesta = staff(roles.EJECUTIVO).get(
            url_archivo(
                "documentos:tramite-documento-archivo",
                tramite,
                documento,
                "pdf",
            ),
        )

        assert respuesta.status_code == HTTPStatus.OK

    def test_staff_without_permission_cannot(self, caso):
        cuenta, tramite, documento = caso
        url = url_archivo(
            "documentos:tramite-documento-archivo",
            tramite,
            documento,
            "pdf",
        )

        assert staff(None).get(url).status_code == HTTPStatus.FORBIDDEN
        assert portal(cuenta).get(url).status_code == HTTPStatus.FORBIDDEN


class TestSubirFirmado:
    def test_completes_the_case_and_puts_the_contract_in_force(
        self,
        caso,
        django_capture_on_commit_callbacks,
    ):
        cuenta, tramite, documento = caso
        tramite = a_firma(tramite, django_capture_on_commit_callbacks)

        respuesta = subir(tramite, documento)

        assert respuesta.status_code == HTTPStatus.OK
        assert respuesta.json()["estado"] == "firmado"
        documento.refresh_from_db()
        assert documento.sha256_firmado == respuesta.json()["sha256_firmado"]
        assert all(f.firmado_en for f in documento.firmantes.all())
        tramite.refresh_from_db()
        assert situacion(tramite) == ("completado", None)
        assert tramite.contrato.estado == Contrato.Estado.VIGENTE
        descarga = portal(cuenta).get(
            url_archivo(
                "portal:tramite-documento-archivo",
                tramite,
                documento,
                "firmado",
            ),
        )
        assert b"".join(descarga.streaming_content) == PDF_FIRMADO

    def test_only_a_pdf_is_accepted(self, caso, django_capture_on_commit_callbacks):
        _, tramite, documento = caso
        tramite = a_firma(tramite, django_capture_on_commit_callbacks)

        disfrazado = subir(tramite, documento, b"MZ\x90\x00 no es pdf", "firmado.pdf")
        otro_formato = subir(tramite, documento, PDF_FIRMADO, "firmado.docx")

        assert disfrazado.status_code == HTTPStatus.BAD_REQUEST
        assert otro_formato.status_code == HTTPStatus.BAD_REQUEST
        assert situacion(tramite) == ("pendiente", "firma")

    def test_not_before_payment(self, caso):
        _, tramite, documento = caso

        respuesta = subir(tramite, documento)

        assert respuesta.status_code == HTTPStatus.CONFLICT
        assert respuesta.json()["codigo"] == "no_firmable"

    def test_a_past_start_date_asks_for_a_new_one(
        self,
        caso,
        django_capture_on_commit_callbacks,
    ):
        _, tramite, documento = caso
        tramite = a_firma(tramite, django_capture_on_commit_callbacks)
        Contrato.objects.filter(pk=tramite.contrato_id).update(
            fecha_inicio=timezone.localdate() - timedelta(days=1),
        )

        respuesta = subir(tramite, documento)

        assert respuesta.status_code == HTTPStatus.CONFLICT
        assert respuesta.json()["codigo"] == "fecha_inicio_vencida"
        tramite.refresh_from_db()
        assert situacion(tramite) == ("pendiente", "falta_informacion")
        assert not Documento.objects.exclude(archivo_firmado="").exists()

    def test_requires_the_upload_permission(self, caso):
        _, tramite, documento = caso

        respuesta = staff(None).post(
            reverse(
                "documentos:tramite-documento-subir-firmado",
                args=[tramite.pk, documento.pk],
            ),
            {"archivo": SimpleUploadedFile("f.pdf", PDF_FIRMADO)},
            format="multipart",
        )

        assert respuesta.status_code == HTTPStatus.FORBIDDEN


class TestAuditoria:
    def test_each_download_is_audited_with_its_channel(self, caso):
        cuenta, tramite, documento = caso

        portal(cuenta).get(
            url_archivo("portal:tramite-documento-archivo", tramite, documento, "pdf"),
        )
        staff(roles.EJECUTIVO).get(
            url_archivo(
                "documentos:tramite-documento-archivo",
                tramite,
                documento,
                "docx",
            ),
        )

        descargas = RegistroAuditoria.objects.filter(
            accion=RegistroAuditoria.Accion.DESCARGA_DOCUMENTO,
            entidad="documentos.documento",
            registro_id=documento.pk,
        ).order_by("pk")
        assert [(d.origen, d.valor_nuevo) for d in descargas] == [
            ("portal", {"archivo": "pdf"}),
            ("api", {"archivo": "docx"}),
        ]
        assert descargas[0].usuario == cuenta.user

    def test_a_missing_file_is_not_audited(self, caso):
        cuenta, tramite, documento = caso

        portal(cuenta).get(
            url_archivo(
                "portal:tramite-documento-archivo",
                tramite,
                documento,
                "firmado",
            ),
        )

        assert not RegistroAuditoria.objects.filter(
            accion=RegistroAuditoria.Accion.DESCARGA_DOCUMENTO,
        ).exists()

    def test_the_generation_and_the_signed_upload_are_in_the_log(
        self,
        caso,
        django_capture_on_commit_callbacks,
    ):
        _, tramite, documento = caso
        tramite = a_firma(tramite, django_capture_on_commit_callbacks)

        assert subir(tramite, documento).status_code == HTTPStatus.OK

        filas = RegistroAuditoria.objects.filter(
            entidad="documentos.documento",
            registro_id=documento.pk,
        ).order_by("pk")
        creacion, firma = filas.first(), filas.last()
        assert creacion.accion == RegistroAuditoria.Accion.CREAR
        assert creacion.origen == "sistema"
        assert "datos_snapshot" not in creacion.valor_nuevo
        assert creacion.valor_nuevo["sha256_pdf"] == documento.sha256_pdf
        assert firma.usuario is not None
        assert firma.origen == "api"
        assert set(firma.valor_nuevo) >= {
            "archivo_firmado",
            "sha256_firmado",
            "firmado_en",
        }

    def test_a_cases_history_includes_its_contract_sale_and_documents(
        self,
        caso,
        django_capture_on_commit_callbacks,
    ):
        _, tramite, _ = caso
        tramite = a_firma(tramite, django_capture_on_commit_callbacks)
        administrador = staff(roles.ADMINISTRADOR)

        respuesta = administrador.get(
            reverse("auditoria:historial"),
            {"entidad": "tramites.tramite", "registro_id": tramite.pk, "page": 1},
        )

        assert respuesta.status_code == HTTPStatus.OK
        todas = {f["entidad"] for f in respuesta.json()["results"]}
        pagina = 2
        while respuesta.json()["next"]:
            respuesta = administrador.get(
                reverse("auditoria:historial"),
                {
                    "entidad": "tramites.tramite",
                    "registro_id": tramite.pk,
                    "page": pagina,
                },
            )
            todas |= {f["entidad"] for f in respuesta.json()["results"]}
            pagina += 1
        assert {
            "tramites.tramite",
            "contratos.contrato",
            "contratos.serviciocontratado",
            "documentos.documento",
            "documentos.firmante",
            "ventas.venta",
            "ventas.itemventa",
            "ventas.ordenpago",
        } <= todas
        assert "clientes.cliente" not in todas
