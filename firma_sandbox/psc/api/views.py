"""The PSC's API (``/api/v1/``), reachable only from the compose network."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from psc import firma as firma_pdf
from psc import pki as pki_mod
from psc import servicios
from psc.estado import estado_solicitud
from psc.models import Firmante
from psc.models import Solicitud

from .serializers import CrearSolicitudSerializer
from .serializers import DatosSolicitudSerializer
from .serializers import EnlaceSerializer
from .serializers import InformeSerializer
from .serializers import SolicitudCreadaSerializer
from .serializers import SolicitudSerializer
from .serializers import ValidarSerializer

if TYPE_CHECKING:
    from rest_framework.request import Request


def _solicitud(request: Request, pk: str) -> Solicitud:
    return get_object_or_404(Solicitud, pk=pk, cliente=request.auth)


def _conflicto(error: Exception) -> Response:
    return Response(
        {"codigo": "no_permitido", "detalle": str(error)},
        status=status.HTTP_409_CONFLICT,
    )


class SolicitudesView(APIView):
    parser_classes = [MultiPartParser]

    @extend_schema(
        summary="Crear una solicitud de firma",
        request={"multipart/form-data": CrearSolicitudSerializer},
        responses={
            201: SolicitudCreadaSerializer,
            400: OpenApiResponse(description="Datos inválidos"),
        },
    )
    def post(self, request: Request) -> Response:
        entrada = CrearSolicitudSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        datos_crudos = entrada.validated_data["datos"]
        if isinstance(datos_crudos, (bytes, str)):
            try:
                datos_crudos = json.loads(datos_crudos)
            except ValueError:
                return Response(
                    {"datos": "Debe ser JSON."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        datos = DatosSolicitudSerializer(data=datos_crudos)
        datos.is_valid(raise_exception=True)
        valores = datos.validated_data
        try:
            solicitud, enlace = servicios.crear_solicitud(
                request.auth,
                entrada.validated_data["documento"].read(),
                nombre_documento=valores["nombre_documento"],
                referencia_externa=valores["referencia_externa"],
                url_notificacion=valores["url_notificacion"],
                expira_en=valores["expira_en"],
                firmantes=[servicios.FirmanteNuevo(**f) for f in valores["firmantes"]],
            )
        except servicios.DatosInvalidosError as error:
            return Response(error.errores, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {**estado_solicitud(solicitud), "url_firma": enlace},
            status=status.HTTP_201_CREATED,
        )


class SolicitudView(APIView):
    @extend_schema(
        summary="Estado de una solicitud y de cada firmante",
        responses=SolicitudSerializer,
    )
    def get(self, request: Request, pk: str) -> Response:
        return Response(estado_solicitud(_solicitud(request, pk)))


class DocumentoView(APIView):
    @extend_schema(
        summary="Descargar el PDF firmado",
        responses={
            (200, "application/pdf"): OpenApiResponse(
                description="El PDF con todas las firmas",
            ),
            409: OpenApiResponse(description="La solicitud no está completada"),
        },
    )
    def get(self, request: Request, pk: str) -> HttpResponse | Response:
        solicitud = _solicitud(request, pk)
        if solicitud.estado != Solicitud.Estado.COMPLETADA:
            return Response(
                {
                    "codigo": "no_completada",
                    "detalle": f"La solicitud está {solicitud.estado}.",
                },
                status=status.HTTP_409_CONFLICT,
            )
        respuesta = HttpResponse(
            bytes(solicitud.documento_actual),
            content_type="application/pdf",
        )
        respuesta["Content-Disposition"] = f'attachment; filename="{solicitud.pk}.pdf"'
        respuesta["X-PSC-Sha256"] = solicitud.sha256_firmado
        return respuesta


class CancelarView(APIView):
    @extend_schema(
        summary="Cancelar una solicitud abierta",
        request=None,
        responses=SolicitudSerializer,
    )
    def post(self, request: Request, pk: str) -> Response:
        try:
            solicitud = servicios.cancelar(_solicitud(request, pk))
        except servicios.OperacionNoPermitidaError as error:
            return _conflicto(error)
        return Response(estado_solicitud(solicitud))


class ReenviarView(APIView):
    @extend_schema(
        summary="Reenviar el enlace a un firmante",
        request=None,
        responses=EnlaceSerializer,
    )
    def post(self, request: Request, pk: str, firmante: str) -> Response:
        solicitud = _solicitud(request, pk)
        objetivo = get_object_or_404(Firmante, pk=firmante, solicitud=solicitud)
        try:
            enlace = servicios.reenviar(objetivo)
        except servicios.OperacionNoPermitidaError as error:
            return _conflicto(error)
        return Response({"url_firma": enlace})


class ValidacionesView(APIView):
    parser_classes = [MultiPartParser]

    @extend_schema(
        summary="Validar un PDF firmado contra la raíz de pruebas",
        request={"multipart/form-data": ValidarSerializer},
        responses=InformeSerializer,
    )
    def post(self, request: Request) -> Response:
        entrada = ValidarSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        informe = firma_pdf.validar(
            entrada.validated_data["documento"].read(),
            pki_mod.cargar(),
        )
        return Response(
            InformeSerializer({**informe.__dict__, "valido": informe.valido}).data,
        )
