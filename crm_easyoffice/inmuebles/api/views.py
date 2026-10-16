"""Protected access to authorisers' identity cards (HU-66)."""

from __future__ import annotations

import mimetypes
from pathlib import PurePath
from typing import TYPE_CHECKING

from django.http import FileResponse
from django.http import Http404
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from drf_spectacular.utils import OpenApiResponse
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import BasePermission
from rest_framework.views import APIView

from crm_easyoffice.inmuebles.models import Autorizante
from crm_easyoffice.inmuebles.services import abrir_documento_identidad

if TYPE_CHECKING:
    from rest_framework.request import Request

PERMISO_DOCUMENTO = "inmuebles.descargar_documento_identidad"


class PuedeVerDocumentoIdentidad(BasePermission):
    def has_permission(self, request: Request, view: APIView) -> bool:
        return bool(
            request.user.is_authenticated and request.user.has_perm(PERMISO_DOCUMENTO),
        )


class DocumentoIdentidadView(APIView):
    """Download an authoriser's identity card.

    Sent as an attachment and never cached, so it does not linger in a
    browser or proxy cache.
    """

    permission_classes = [PuedeVerDocumentoIdentidad]

    @extend_schema(
        parameters=[OpenApiParameter("lado", str, enum=["anverso", "reverso"])],
        responses={(200, "*/*"): OpenApiResponse(OpenApiTypes.BINARY)},
    )
    def get(self, request: Request, pk: int) -> FileResponse:
        autorizante = get_object_or_404(Autorizante, pk=pk)
        reverso = request.query_params.get("lado") == "reverso"
        try:
            archivo = abrir_documento_identidad(autorizante, reverso=reverso)
        except FileNotFoundError as error:
            raise Http404 from error

        lado = "reverso" if reverso else "anverso"
        extension = PurePath(archivo.name).suffix.lower()
        content_type = mimetypes.types_map.get(extension, "application/octet-stream")
        response = FileResponse(
            archivo,
            as_attachment=True,
            filename=f"cedula-autorizante-{autorizante.pk}-{lado}{extension}",
            content_type=content_type,
        )
        response["Cache-Control"] = "no-store, private"
        response["X-Content-Type-Options"] = "nosniff"
        return response
