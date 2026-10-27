"""The signer's pages: open the link, read the PDF and the warning, prove
identity, get the code, consent and sign, or decline with a reason."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from django.http import Http404
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_http_methods

from psc import servicios
from psc.models import Firmante
from psc.models import Solicitud

if TYPE_CHECKING:
    from django.http import HttpRequest


def _firmante(token: str) -> Firmante:
    firmante = servicios.firmante_por_token(token)
    if firmante is None:
        raise Http404
    return firmante


def _paso(firmante: Firmante) -> str:
    solicitud = firmante.solicitud
    if firmante.estado != Firmante.Estado.PENDIENTE:
        return firmante.estado
    if not solicitud.abierta:
        return "cerrada"
    if not servicios.es_su_turno(firmante):
        return "espera"
    if firmante.bloqueado and not firmante.identidad_verificada_en:
        return "bloqueado"
    return "codigo" if firmante.identidad_verificada_en else "identidad"


NO_COINCIDE = (
    "Los datos no coinciden con el registro. Revisa tu RUT y el número de serie."
)


def _identidad(request: HttpRequest, firmante: Firmante) -> dict[str, str]:
    datos = {
        "rut": request.POST.get("rut", ""),
        "numero_serie": request.POST.get("numero_serie", ""),
    }
    if not servicios.verificar_identidad(firmante, datos):
        return {"error": NO_COINCIDE}
    return {"mensaje": "Identidad verificada. Pide tu código para firmar."}


def _codigo(request: HttpRequest, firmante: Firmante) -> dict[str, str]:
    servicios.enviar_codigo(firmante)
    return {"mensaje": "Te enviamos un código a tu correo."}


def _firmar(request: HttpRequest, firmante: Firmante) -> dict[str, str]:
    servicios.firmar(
        firmante,
        request.POST.get("codigo", ""),
        consiente=request.POST.get("consiento") == "si",
    )
    return {"mensaje": "Documento firmado."}


def _rechazar(request: HttpRequest, firmante: Firmante) -> dict[str, str]:
    servicios.rechazar(firmante, request.POST.get("motivo", ""))
    return {"mensaje": "Registramos tu rechazo."}


ACCIONES = {
    "identidad": _identidad,
    "codigo": _codigo,
    "firmar": _firmar,
    "rechazar": _rechazar,
}


def _accion(request: HttpRequest, firmante: Firmante) -> dict[str, Any]:
    accion = ACCIONES.get(request.POST.get("accion", ""))
    if accion is None:
        return {"error": "Acción desconocida."}
    try:
        return accion(request, firmante)
    except servicios.OperacionNoPermitidaError as error:
        return {"error": str(error)}


@require_http_methods(["GET", "POST"])
def firmar(request: HttpRequest, token: str) -> HttpResponse:
    firmante = _firmante(token)
    contexto: dict[str, Any] = {}
    if request.method == "POST":
        contexto = _accion(request, firmante)
        firmante.refresh_from_db()
        firmante.solicitud.refresh_from_db()
    contexto |= {
        "firmante": firmante,
        "solicitud": firmante.solicitud,
        "paso": _paso(firmante),
        "token": token,
    }
    estado = 400 if contexto.get("error") else 200
    return render(request, "psc/firmar.html", contexto, status=estado)


@require_GET
def documento(request: HttpRequest, token: str) -> HttpResponse:
    """The document as it stands now, for the signer to read before signing."""
    firmante = _firmante(token)
    respuesta = HttpResponse(
        bytes(firmante.solicitud.documento_actual),
        content_type="application/pdf",
    )
    respuesta["Content-Disposition"] = 'inline; filename="documento.pdf"'
    respuesta["Cache-Control"] = "no-store"
    return respuesta


@require_GET
def verificar(request: HttpRequest, codigo: str) -> HttpResponse:
    """Check a signature's verification code, as printed on its stamp."""
    firmante = (
        Firmante.objects.select_related("solicitud")
        .filter(codigo_verificacion=codigo.upper(), estado=Firmante.Estado.FIRMADO)
        .first()
    )
    contexto = {
        "codigo": codigo,
        "firmante": firmante,
        "completada": firmante is not None
        and firmante.solicitud.estado == Solicitud.Estado.COMPLETADA,
    }
    return render(
        request,
        "psc/verificar.html",
        contexto,
        status=200 if firmante else 404,
    )
