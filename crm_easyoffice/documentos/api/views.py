"""A case's documents: versions, protected downloads and the signed upload.

Files live in private storage and have no URL; these views check who asks
and send them uncached.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError as DjangoValidationError
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
from crm_easyoffice.core.auditoria.eventos import Accion
from crm_easyoffice.core.auditoria.eventos import registrar_evento
from crm_easyoffice.documentos.models import (
    Documento,  # noqa: TC001 - runtime use in _documentos
)
from crm_easyoffice.documentos.services import DocumentoNoFirmableError
from crm_easyoffice.documentos.services import registrar_firmado
from crm_easyoffice.tramites.models import Tramite
from crm_easyoffice.tramites.services import FechaInicioVencidaError

from .serializers import DocumentoSerializer

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


def _documentos(tramite: Tramite) -> QuerySet[Documento]:
    return tramite.documentos.select_related(
        "version_plantilla__plantilla",
    ).prefetch_related(
        "firmantes__persona",
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
    registrar_evento(
        Accion.DESCARGA_DOCUMENTO,
        entidad="documentos.documento",
        registro_id=documento.pk,
        datos={"archivo": tipo},
    )
    return response


class _DocumentosBase(APIView):
    def tramite(self, request: Request, tramite_id: int) -> Tramite:
        raise NotImplementedError

    @extend_schema(responses=DocumentoSerializer(many=True))
    def get(self, request: Request, tramite_id: int) -> Response:
        tramite = self.tramite(request, tramite_id)
        return Response(DocumentoSerializer(_documentos(tramite), many=True).data)


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


class DocumentosPortalView(_DelCliente, _DocumentosBase):
    """The versions of the client's own case."""


class DescargaPortalView(_DelCliente, _DescargaBase):
    """The PDF (inline), the Word file or the signed PDF of the client's case."""


class DocumentosBackofficeView(_DeStaff, _DocumentosBase):
    """The versions of any case, for staff with view_documento."""


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
            DocumentoSerializer(_documentos(tramite).get(pk=documento.pk)).data,
        )
