"""Consultation of the audit log (HU-31, RF-17, UC-13). Read-only by design."""

from __future__ import annotations

from datetime import datetime
from datetime import time
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Any

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import BasePermission

from crm_easyoffice.core.auditoria.consulta import historial
from crm_easyoffice.core.auditoria.consulta import nombres_registros
from crm_easyoffice.core.models import RegistroAuditoria

from .serializers import FiltrosAuditoriaSerializer
from .serializers import HistorialSerializer
from .serializers import RegistroAuditoriaSerializer

if TYPE_CHECKING:
    from datetime import date

    from django.db.models import QuerySet
    from rest_framework.request import Request

PERMISO_AUDITORIA = "core.consultar_auditoria"


class PuedeConsultarAuditoria(BasePermission):
    """Only the Administrador (RN-31); never the Ejecutivo nor a client."""

    def has_permission(self, request: Request, view: Any) -> bool:
        return bool(
            request.user.is_authenticated and request.user.has_perm(PERMISO_AUDITORIA),
        )


class AuditoriaPagination(PageNumberPagination):
    page_size = 25


def _inicio_del_dia(dia: date) -> datetime:
    return timezone.make_aware(datetime.combine(dia, time.min))


class _ListaAuditoria(ListAPIView):
    permission_classes = [PuedeConsultarAuditoria]
    pagination_class = AuditoriaPagination
    serializer_class = RegistroAuditoriaSerializer

    def paginate_queryset(self, queryset: QuerySet[RegistroAuditoria]):
        pagina = super().paginate_queryset(queryset)
        self.page_entries = list(pagina) if pagina is not None else []
        return pagina

    def get_serializer_context(self) -> dict[str, Any]:
        contexto = super().get_serializer_context()
        contexto["nombres"] = nombres_registros(getattr(self, "page_entries", []))
        return contexto


@extend_schema(parameters=[FiltrosAuditoriaSerializer])
class RegistroAuditoriaListView(_ListaAuditoria):
    """The audit log with filters, newest first."""

    def get_queryset(self) -> QuerySet[RegistroAuditoria]:
        filtros = FiltrosAuditoriaSerializer(data=self.request.query_params)
        filtros.is_valid(raise_exception=True)
        datos = filtros.validated_data
        entradas = RegistroAuditoria.objects.select_related("usuario")
        for campo in ("entidad", "registro_id", "accion", "origen"):
            if campo in datos:
                entradas = entradas.filter(**{campo: datos[campo]})
        if "usuario" in datos:
            entradas = entradas.filter(usuario_id=datos["usuario"])
        if "desde" in datos:
            entradas = entradas.filter(fecha_hora__gte=_inicio_del_dia(datos["desde"]))
        if "hasta" in datos:
            fin = _inicio_del_dia(datos["hasta"] + timedelta(days=1))
            entradas = entradas.filter(fecha_hora__lt=fin)
        return entradas


@extend_schema(parameters=[HistorialSerializer])
class HistorialView(_ListaAuditoria):
    """A record's history, with the records that belong to it.

    A client's includes its persona or empresa, its representatives and its
    portal account; a case's, its contract and lines, its sale and payments,
    and its documents and signers (``core.auditoria.registro.HISTORIAL``).
    """

    def get_queryset(self) -> QuerySet[RegistroAuditoria]:
        parametros = HistorialSerializer(data=self.request.query_params)
        parametros.is_valid(raise_exception=True)
        datos = parametros.validated_data
        return historial(datos["entidad"], datos["registro_id"]).select_related(
            "usuario",
        )
