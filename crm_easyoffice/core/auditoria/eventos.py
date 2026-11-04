"""Audit entries that are not row changes: accesses and sign-ins (RN-36, RS-04).

Row changes are recorded by the database triggers. What changes no row, such
as signing in or downloading a document, is recorded here, in the same table
and with the same user, address and channel as the triggers would use.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from django.contrib.auth import get_user_model

from crm_easyoffice.core.models import RegistroAuditoria

from .contexto import valores_actuales

if TYPE_CHECKING:
    from django.http import HttpRequest

Accion = RegistroAuditoria.Accion


def registrar_evento(
    accion: str,
    *,
    entidad: str = "",
    registro_id: int | None = None,
    datos: dict[str, Any] | None = None,
    usuario: Any = None,
) -> RegistroAuditoria:
    """Record an access or action that changes no row.

    The user, IP and channel come from the current audit context (the
    request, or ``sistema``); ``usuario`` replaces the user when the context
    does not have it yet, as during a sign-in.
    """
    valores = valores_actuales()
    return RegistroAuditoria.objects.create(
        usuario_id=usuario.pk if usuario is not None else valores.usuario_id,
        origen=valores.origen,
        accion=accion,
        entidad=entidad,
        registro_id=registro_id,
        valor_nuevo=datos,
        direccion_ip=valores.ip,
    )


def al_iniciar_sesion(
    sender: Any,
    request: HttpRequest,
    user: Any,
    **kwargs: Any,
) -> None:
    registrar_evento(
        Accion.INICIO_SESION,
        entidad="users.user",
        registro_id=user.pk,
        usuario=user,
    )


def al_cerrar_sesion(
    sender: Any,
    request: HttpRequest,
    user: Any,
    **kwargs: Any,
) -> None:
    if user is None:
        return
    registrar_evento(
        Accion.CIERRE_SESION,
        entidad="users.user",
        registro_id=user.pk,
        usuario=user,
    )


def al_fallar_inicio_sesion(
    sender: Any,
    credentials: dict[str, Any],
    request: HttpRequest | None = None,
    **kwargs: Any,
) -> None:
    # ASSUMPTION: pending validation with Easy Office. Failed sign-ins are
    # kept with the address that was typed, to spot attempts against an
    # account; the password never reaches this function (Django masks it).
    # The account goes in registro_id, not in usuario: who tried is unknown.
    email = str(credentials.get("username") or credentials.get("email") or "")[:254]
    usuario = (
        get_user_model().objects.filter(email__iexact=email).first() if email else None
    )
    registrar_evento(
        Accion.INICIO_SESION_FALLIDO,
        entidad="users.user",
        registro_id=usuario.pk if usuario else None,
        datos={"email": email},
    )
