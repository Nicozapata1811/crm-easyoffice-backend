from collections.abc import Iterable
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from django.core.files.uploadedfile import UploadedFile
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiParameter
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser
from rest_framework.parsers import JSONParser
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from crm_easyoffice.integrations.sitio_web.base import ProspectoEntrante
from crm_easyoffice.integrations.sitio_web.base import UnknownAdapterError
from crm_easyoffice.integrations.sitio_web.registry import DEFAULT_ADAPTER
from crm_easyoffice.integrations.sitio_web.registry import get_adapter
from crm_easyoffice.prospectos.services import registrar_prospecto

from .permissions import WebhookSitioTokenPermission
from .serializers import ProspectoEntranteSerializer
from .serializers import ResultadoWebhookSerializer
from .throttling import WebhookSitioThrottle


class ProspectoWebhookView(APIView):
    """Receives the public website's form submissions as leads.

    Contract: docs/integration/website-contract.md.
    """

    authentication_classes = []
    permission_classes = [WebhookSitioTokenPermission]
    throttle_classes = [WebhookSitioThrottle]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def check_permissions(self, request):
        super().check_throttles(request)
        super().check_permissions(request)

    def check_throttles(self, request):
        """Already applied in check_permissions, ahead of the token check."""

    @extend_schema(
        parameters=[
            OpenApiParameter("token", str, required=True),
            OpenApiParameter("formato", str, default=DEFAULT_ADAPTER),
        ],
        request=ProspectoEntranteSerializer,
        responses={
            HTTPStatus.CREATED: ResultadoWebhookSerializer,
            HTTPStatus.OK: ResultadoWebhookSerializer,
        },
    )
    def post(self, request):
        formato = request.query_params.get("formato", DEFAULT_ADAPTER)
        try:
            adapter = get_adapter(formato)
        except UnknownAdapterError as exc:
            raise ValidationError({"formato": [_("Unknown format.")]}) from exc

        if not isinstance(request.data, Mapping):
            raise ValidationError(_("Expected an object of fields."))

        serializer = ProspectoEntranteSerializer(data=adapter.parse(request.data))
        serializer.is_valid(raise_exception=True)
        entrante = ProspectoEntrante(
            **serializer.validated_data,
            recibido_en=timezone.now(),
            payload_original=payload_original(request.data),
        )

        _prospecto, creado = registrar_prospecto(entrante, formato=formato)
        if creado:
            return Response({"resultado": "creado"}, status=HTTPStatus.CREATED)
        return Response({"resultado": "duplicado"}, status=HTTPStatus.OK)


def payload_original(data: Mapping[str, Any]) -> dict[str, Any]:
    """The submitted fields as received, without file contents."""
    items: Iterable[tuple[str, Any]]
    if hasattr(data, "lists"):
        items = ((k, v[0] if len(v) == 1 else v) for k, v in data.lists())
    else:
        items = data.items()
    return {
        key: value
        for key, value in items
        if not isinstance(value, UploadedFile)
        and not (
            isinstance(value, list) and any(isinstance(v, UploadedFile) for v in value)
        )
    }
