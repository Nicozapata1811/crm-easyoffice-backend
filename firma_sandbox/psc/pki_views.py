"""Public PKI endpoints: the CA certificates, the CRLs, OCSP and the TSA."""

from __future__ import annotations

from typing import TYPE_CHECKING

from asn1crypto import tsp
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.x509 import ocsp
from django.http import Http404
from django.http import HttpResponse
from django.http import HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_POST

from . import pki as pki_mod
from .firma import timestamper
from .models import Certificado
from .servicios import revocados

if TYPE_CHECKING:
    from django.http import HttpRequest

DER = serialization.Encoding.DER


@require_GET
def certificado(request: HttpRequest, nombre: str) -> HttpResponse:
    pki = pki_mod.cargar()
    certs = {"raiz": pki.raiz, "emisora": pki.emisora, "tsa": pki.tsa}
    if nombre not in certs:
        raise Http404
    respuesta = HttpResponse(
        certs[nombre].public_bytes(DER),
        content_type="application/pkix-cert",
    )
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre}-pruebas.crt"'
    return respuesta


@require_GET
def crl(request: HttpRequest, nombre: str) -> HttpResponse:
    pki = pki_mod.cargar()
    if nombre == "raiz":
        lista = pki_mod.lista_revocacion(pki.raiz, pki.clave_raiz)
    elif nombre == "emisora":
        lista = pki_mod.lista_revocacion(pki.emisora, pki.clave_emisora, revocados())
    else:
        raise Http404
    return HttpResponse(lista.public_bytes(DER), content_type="application/pkix-crl")


@csrf_exempt
@require_POST
def respondedor_ocsp(request: HttpRequest) -> HttpResponse:
    try:
        consulta = ocsp.load_der_ocsp_request(request.body)
    except ValueError:
        return HttpResponseBadRequest()
    registro = Certificado.objects.filter(
        numero_serie=str(consulta.serial_number),
    ).first()
    if registro is None:
        respuesta = pki_mod.respuesta_ocsp_desconocida()
    else:
        cert = x509.load_pem_x509_certificate(registro.pem.encode())
        respuesta = pki_mod.respuesta_ocsp(pki_mod.cargar(), cert, registro.revocado_en)
    return HttpResponse(
        respuesta.public_bytes(DER),
        content_type="application/ocsp-response",
    )


@csrf_exempt
@require_POST
def tsa(request: HttpRequest) -> HttpResponse:
    """RFC 3161 over HTTP, for tools that want to timestamp against the test TSA."""
    try:
        consulta = tsp.TimeStampReq.load(request.body)
        consulta.native  # noqa: B018 - parse eagerly, so a malformed request fails here
    except ValueError:
        return HttpResponseBadRequest()
    respuesta = timestamper(pki_mod.cargar()).request_tsa_response(consulta)
    return HttpResponse(respuesta.dump(), content_type="application/timestamp-reply")
