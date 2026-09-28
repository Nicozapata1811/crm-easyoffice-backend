from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from crm_easyoffice.tramites.catalogo import listar_servicios

from .serializers import CatalogoSerializer


class CatalogoView(APIView):
    """Public, read-only: the portal resolves deep links before any login."""

    permission_classes = [AllowAny]

    @extend_schema(responses=CatalogoSerializer)
    def get(self, request):
        serializer = CatalogoSerializer({"servicios": listar_servicios()})
        return Response(serializer.data)
