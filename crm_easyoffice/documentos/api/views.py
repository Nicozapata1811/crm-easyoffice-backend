"""A case's documents: versions, protected downloads and the signed upload.

Files live in private storage and have no URL; these views check who asks
and send them uncached.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Prefetch
from django.http import FileResponse
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from crm_easyoffice.clientes.api.permissions import EsCliente
from crm_easyoffice.documentos import firma
from crm_easyoffice.documentos import tasks
from crm_easyoffice.documentos.models import Documento
from crm_easyoffice.documentos.models import SolicitudFirma
from crm_easyoffice.documentos.services import DocumentoNoFirmableError
from crm_easyoffice.documentos.services import FirmaAvanzadaError
from crm_easyoffice.documentos.services import registrar_firmado
from crm_easyoffice.tramites.models import Tramite
from crm_easyoffice.tramites.services import FechaInicioVencidaError

from .serializers import DocumentoBackofficeSerializer
from .serializers import DocumentoSerializer
from .serializers import ReenviarFirmaSerializer

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from rest_framework.request import Request

ARCHIVOS = {
    "pdf": ("archivo_pdf", "application/pdf", False),
    "docx": (
        "archivo_docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        True,
    ),
    "firmado": ("archivo_firmado", "application/pdf", True),
}


class TienePermiso(BasePermission):
    permiso = ""

    def has_permission(self, request: Request, view) -> bool:
        return bool(
            request.user.is_authenticated and request.user.has_perm(self.permiso),
        )


class PuedeVerDocumentos(TienePermiso):
    permiso = "documentos.view_documento"


class PuedeSubirFirmado(TienePermiso):
    permiso = "documentos.subir_documento_firmado"


class PuedeGestionarFirma(TienePermiso):
    permiso = "documentos.gestionar_firma"


def _documentos(tramite: Tramite) -> QuerySet[Documento]:
    return tramite.documentos.select_related(
        "version_plantilla__plantilla",
        "tramite__tipo",
    ).prefetch_related(
        "firmantes__persona",
        Prefetch(
            "solicitudes_firma",
            queryset=SolicitudFirma.objects.order_by("-created_at", "-pk"),
        ),
    )


def _descargar(documento: Documento, tipo: str) -> FileResponse:
    if tipo not in ARCHIVOS:
        raise Http404
    campo, content_type, adjunto = ARCHIVOS[tipo]
    archivo = getattr(documento, campo)
    if not archivo:
        raise Http404
    extension = "docx" if tipo == "docx" else "pdf"
    sufijo = "-firmado" if tipo == "firmado" else f"-v{documento.version}"
    response = FileResponse(
        archivo.open("rb"),
        as_attachment=adjunto,
        filename=f"{documento.tramite.contrato.folio}{sufijo}.{extension}",
        content_type=content_type,
    )
    response["Cache-Control"] = "no-store, private"
    response["X-Content-Type-Options"] = "nosniff"
    # TODO(RF-15): record each download in the audit log (HU-30).
    return response


class _DocumentosBase(APIView):
    serializer_class = DocumentoSerializer

    def tramite(self, request: Request, tramite_id: int) -> Tramite:
        raise NotImplementedError

    def get(self, request: Request, tramite_id: int) -> Response:
        tramite = self.tramite(request, tramite_id)
        documentos = _documentos(tramite)
        vigente = next((d for d in documentos if d.estado == d.Estado.GENERADO), None)
        if vigente is not None and (solicitud := firma.por_sincronizar(vigente)):
            # The fallback when a webhook is lost: ask the provider again.
            transaction.on_commit(
                lambda: tasks.sincronizar_solicitud_firma.delay(solicitud.pk),
            )
        return Response(self.serializer_class(documentos, many=True).data)


class _DescargaBase(APIView):
    def tramite(self, request: Request, tramite_id: int) -> Tramite:
        raise NotImplementedError

    @extend_schema(responses={(200, "*/*"): OpenApiResponse(OpenApiTypes.BINARY)})
    def get(
        self,
        request: Request,
        tramite_id: int,
        pk: int,
        tipo: str,
    ) -> FileResponse:
        tramite = self.tramite(request, tramite_id)
        documento = get_object_or_404(tramite.documentos, pk=pk)
        return _descargar(documento, tipo)


class _DelCliente:
    permission_classes = [EsCliente]

    def tramite(self, request: Request, tramite_id: int) -> Tramite:
        cliente = request.user.cuenta_cliente.cliente
        return get_object_or_404(Tramite, pk=tramite_id, cliente=cliente)


class _DeStaff:
    permission_classes = [PuedeVerDocumentos]

    def tramite(self, request: Request, tramite_id: int) -> Tramite:
        return get_object_or_404(Tramite, pk=tramite_id)


@extend_schema(responses=DocumentoSerializer(many=True))
class DocumentosPortalView(_DelCliente, _DocumentosBase):
    """The versions of the client's own case."""


class DescargaPortalView(_DelCliente, _DescargaBase):
    """The PDF (inline), the Word file or the signed PDF of the client's case."""


@extend_schema(responses=DocumentoBackofficeSerializer(many=True))
class DocumentosBackofficeView(_DeStaff, _DocumentosBase):
    """The versions of any case, for staff with view_documento."""

    serializer_class = DocumentoBackofficeSerializer


class DescargaBackofficeView(_DeStaff, _DescargaBase):
    """Any case's files, for staff with view_documento."""


class FirmadoSerializer(serializers.Serializer):
    archivo = serializers.FileField()


class SubirFirmadoView(APIView):
    """The executive uploads the signed PDF (assisted signature)."""

    permission_classes = [PuedeSubirFirmado]
    parser_classes = [MultiPartParser]

    @extend_schema(
        request={"multipart/form-data": FirmadoSerializer},
        responses=DocumentoSerializer,
    )
    def post(self, request: Request, tramite_id: int, pk: int) -> Response:
        tramite = get_object_or_404(Tramite, pk=tramite_id)
        documento = get_object_or_404(tramite.documentos, pk=pk)
        serializer = FirmadoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            documento = registrar_firmado(
                documento,
                serializer.validated_data["archivo"],
                request.user,
            )
        except DjangoValidationError as error:
            raise ValidationError(error.message_dict) from error
        except FirmaAvanzadaError:
            return Response(
                {
                    "detail": _(
                        "This case type is signed through the signature provider.",
                    ),
                    "codigo": "firma_avanzada",
                },
                status=status.HTTP_409_CONFLICT,
            )
        except DocumentoNoFirmableError:
            return Response(
                {
                    "detail": _("This document is not waiting for a signature."),
                    "codigo": "no_firmable",
                },
                status=status.HTTP_409_CONFLICT,
            )
        except FechaInicioVencidaError:
            return Response(
                {
                    "detail": _(
                        "The start date has passed: the client must choose a new "
                        "one before signing.",
                    ),
                    "codigo": "fecha_inicio_vencida",
                },
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            DocumentoBackofficeSerializer(
                _documentos(tramite).get(pk=documento.pk),
            ).data,
        )


class _FirmaAccionBase(APIView):
    """An executive's action on an advanced signature. The provider is called
    in Celery; the answer is the document as it stands."""

    permission_classes = [PuedeGestionarFirma]

    def accion(self, request: Request, documento: Documento) -> None:
        raise NotImplementedError

    @extend_schema(request=None, responses={202: DocumentoBackofficeSerializer})
    def post(self, request: Request, tramite_id: int, pk: int) -> Response:
        tramite = get_object_or_404(Tramite, pk=tramite_id)
        documento = get_object_or_404(tramite.documentos, pk=pk)
        try:
            self.accion(request, documento)
        except firma.FirmaNoGestionableError as error:
            return Response(
                {"detail": str(error), "codigo": "firma_no_gestionable"},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            DocumentoBackofficeSerializer(
                _documentos(tramite).get(pk=documento.pk),
            ).data,
            status=status.HTTP_202_ACCEPTED,
        )


class ReenviarFirmaView(_FirmaAccionBase):
    """Send a pending signer a new signing link."""

    @extend_schema(request=ReenviarFirmaSerializer)
    def post(self, request: Request, tramite_id: int, pk: int) -> Response:
        return super().post(request, tramite_id, pk)

    def accion(self, request: Request, documento: Documento) -> None:
        datos = ReenviarFirmaSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        solicitud_id, externo = firma.preparar_reenvio(
            documento,
            datos.validated_data["firmante"],
        )
        transaction.on_commit(
            lambda: tasks.reenviar_enlace_firma.delay(solicitud_id, externo),
        )


class CancelarFirmaView(_FirmaAccionBase):
    """Cancel the request at the provider; the case goes back to the executive."""

    def accion(self, request: Request, documento: Documento) -> None:
        solicitud_id = firma.preparar_cancelacion(documento)
        usuario_id = request.user.pk
        transaction.on_commit(
            lambda: tasks.cancelar_solicitud_firma.delay(solicitud_id, usuario_id),
        )


class ReintentarFirmaView(_FirmaAccionBase):
    """Send again a request that failed."""

    def accion(self, request: Request, documento: Documento) -> None:
        tramite_id = firma.preparar_reintento(documento)
        transaction.on_commit(lambda: tasks.enviar_a_firma.delay(tramite_id))
