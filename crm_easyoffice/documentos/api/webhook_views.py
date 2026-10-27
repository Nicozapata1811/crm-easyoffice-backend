"""The signature provider's webhooks (IN-01).

Verified (HMAC and timestamp window), recorded once per event id in
``EventoFirma``, and processed in Celery. The view makes no outbound call and
answers fast, as providers expect.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import IntegrityError
from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from crm_easyoffice.documentos.models import EventoFirma
from crm_easyoffice.documentos.models import SolicitudFirma
from crm_easyoffice.documentos.tasks import procesar_evento_firma
from crm_easyoffice.integrations.signature.base import SignatureError
from crm_easyoffice.integrations.signature.registry import get_signature_provider

if TYPE_CHECKING:
    from rest_framework.request import Request


def _payload(cuerpo: bytes) -> dict:
    try:
        datos = json.loads(cuerpo)
    except ValueError:
        return {"no_json": cuerpo[:2000].decode(errors="replace")}
    return datos if isinstance(datos, dict) else {"valor": datos}


def _registrar(**campos) -> EventoFirma | None:
    """Record the event; None if another request recorded it first."""
    try:
        with transaction.atomic():
            return EventoFirma.objects.create(**campos)
    except IntegrityError:
        return None


class FirmaWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(exclude=True)
    def post(self, request: Request, proveedor: str) -> Response:
        if proveedor != settings.SIGNATURE_PROVIDER:
            return Response(status=status.HTTP_404_NOT_FOUND)
        cuerpo = request.body
        try:
            evento = get_signature_provider().parse_webhook(
                cuerpo,
                dict(request.headers),
            )
        except SignatureError:
            _registrar(
                proveedor=proveedor,
                clave_dedup=hashlib.sha256(b"invalida:" + cuerpo).hexdigest(),
                payload=_payload(cuerpo),
                resultado=EventoFirma.Resultado.FIRMA_INVALIDA,
            )
            return Response(
                {"detail": "Invalid signature."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        clave = hashlib.sha256(f"{proveedor}:{evento.event_id}".encode()).hexdigest()
        if EventoFirma.objects.filter(clave_dedup=clave).exists():
            return Response({"status": "duplicado"})
        solicitud = SolicitudFirma.objects.filter(
            proveedor=proveedor,
            id_externo=evento.result.external_id,
        ).first()
        registrado = _registrar(
            solicitud=solicitud,
            proveedor=proveedor,
            id_evento=evento.event_id,
            tipo=str(evento.type),
            clave_dedup=clave,
            payload=_payload(cuerpo),
            resultado=(
                EventoFirma.Resultado.RECIBIDO
                if solicitud is not None
                else EventoFirma.Resultado.IGNORADO
            ),
        )
        if registrado is None:
            return Response({"status": "duplicado"})
        if solicitud is not None:
            transaction.on_commit(lambda: procesar_evento_firma.delay(registrado.pk))
        # TODO(RF-15): record the webhook received in the audit log (HU-30).
        return Response({"status": "ok"})
