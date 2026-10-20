"""Case state changes and the domicile flow (HU-24). The only writer of cases.

Every move goes through ``_mover``, which checks ``TRANSICIONES`` and writes
an EventoTramite. A state is (estado, motivo); RN-42 keeps the reason only
while the case is pending.

The domicile flow is built directly, as the build order asks: it reads the
case type's configuration, never its name.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Case
from django.db.models import Count
from django.db.models import OuterRef
from django.db.models import Q
from django.db.models import Subquery
from django.db.models import Sum
from django.db.models import When
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.translation import gettext as _

from crm_easyoffice.clientes.services import datos_contratante
from crm_easyoffice.clientes.services import guardar_datos_contratante
from crm_easyoffice.configuracion.services import marcas_activas
from crm_easyoffice.configuracion.services import problemas_para_contrato
from crm_easyoffice.contratos.services import LineaContrato
from crm_easyoffice.contratos.services import activar_contrato
from crm_easyoffice.contratos.services import actualizar_borrador
from crm_easyoffice.contratos.services import contacto_de_aviso
from crm_easyoffice.contratos.services import crear_contrato
from crm_easyoffice.inmuebles.services import problemas_para_domicilio
from crm_easyoffice.inmuebles.services import sucursales_activas
from crm_easyoffice.inmuebles.services import sucursales_para_domicilio
from crm_easyoffice.ventas.models import Venta
from crm_easyoffice.ventas.services import PlanNoDisponibleError
from crm_easyoffice.ventas.services import VentaNoPagableError
from crm_easyoffice.ventas.services import anular_venta
from crm_easyoffice.ventas.services import crear_venta
from crm_easyoffice.ventas.services import lineas_de_plan
from crm_easyoffice.ventas.services import planes_en_portal

from .models import EventoTramite
from .models import MotivoPendiente
from .models import TipoTramite
from .models import Tramite
from .signals import documento_requerido

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from crm_easyoffice.clientes.models import Cliente
    from crm_easyoffice.inmuebles.models import Oficina
    from crm_easyoffice.users.models import User
    from crm_easyoffice.ventas.models import PlanServicio

logger = logging.getLogger(__name__)

TIPO_DOMICILIO = "domicilio-tributario"

INICIADO = Tramite.Estado.INICIADO
PENDIENTE = Tramite.Estado.PENDIENTE
COMPLETADO = Tramite.Estado.COMPLETADO

FALTA_INFORMACION = "falta_informacion"
REVISION_BORRADOR = "revision_borrador"
PAGO = "pago"
FIRMA = "firma"

Situacion = tuple[str, str | None]

# ASSUMPTION: pending validation with Easy Office. RN-42 fixes the states;
# the moves between them are proposed.
TRANSICIONES: dict[Situacion, set[Situacion]] = {
    (INICIADO, None): {
        (PENDIENTE, REVISION_BORRADOR),
        (PENDIENTE, FIRMA),
        (PENDIENTE, FALTA_INFORMACION),
    },
    (PENDIENTE, REVISION_BORRADOR): {
        (INICIADO, None),
        (PENDIENTE, PAGO),
        (PENDIENTE, FIRMA),
    },
    (PENDIENTE, PAGO): {
        (INICIADO, None),
        (PENDIENTE, FIRMA),
        (PENDIENTE, FALTA_INFORMACION),
    },
    (PENDIENTE, FALTA_INFORMACION): {
        (INICIADO, None),
    },
    (PENDIENTE, FIRMA): {
        (COMPLETADO, None),
        (PENDIENTE, FALTA_INFORMACION),
    },
    (COMPLETADO, None): set(),
}

NUEVA_FECHA = "La fecha de inicio ya pasó: elige una nueva para emitir el contrato."
SOLO_EMPRESAS = (
    "El domicilio tributario en línea es para empresas. Escríbenos y te ayudamos "
    "a contratarlo."
)


class TransicionInvalidaError(Exception):
    """The case cannot move from its current state to the one asked."""


class TramiteNoDisponibleError(Exception):
    """The online case cannot be offered; ``detalle`` says why, for staff."""

    def __init__(self, detalle: list[str]) -> None:
        super().__init__("; ".join(detalle))
        self.detalle = detalle


class FechaInicioVencidaError(Exception):
    """The start date has passed: a contract is never backdated."""


def situacion(tramite: Tramite) -> Situacion:
    return tramite.estado, tramite.motivo.codigo if tramite.motivo_id else None


def _mover(
    tramite: Tramite,
    estado: str,
    motivo: str | None = None,
    *,
    detalle: str = "",
    usuario: User | None = None,
) -> Tramite:
    """Move a case, if the table allows it, and record the move."""
    with transaction.atomic():
        tramite = Tramite.objects.select_for_update().get(pk=tramite.pk)
        antes = situacion(tramite)
        if (estado, motivo) not in TRANSICIONES[antes]:
            msg = f"{tramite}: {antes} → {(estado, motivo)} is not allowed."
            raise TransicionInvalidaError(msg)
        tramite.estado = estado
        tramite.motivo = MotivoPendiente.objects.get(codigo=motivo) if motivo else None
        tramite.detalle_pendiente = detalle if estado == PENDIENTE else ""
        tramite.save(
            update_fields=["estado", "motivo", "detalle_pendiente", "updated_at"],
        )
        EventoTramite.objects.create(
            tramite=tramite,
            estado_anterior=antes[0],
            motivo_anterior=antes[1] or "",
            estado_nuevo=estado,
            motivo_nuevo=motivo or "",
            detalle=detalle,
            usuario=usuario,
        )
    return tramite


def tipo_domicilio() -> TipoTramite:
    return TipoTramite.objects.get(codigo=TIPO_DOMICILIO)


def ventana_fecha_inicio(
    tipo: TipoTramite,
    hoy: date | None = None,
) -> tuple[date, date]:
    """First and last start date the client may choose: today … +N days.

    ASSUMPTION: pending validation with Easy Office. N defaults to 30.
    """
    hoy = hoy or timezone.localdate()
    return hoy, hoy + timedelta(days=tipo.configuracion.get("inicio_max_dias", 30))


def _requiere(tipo: TipoTramite, paso: str) -> bool:
    return bool(tipo.configuracion.get(paso, True))


def no_disponible(cliente: Cliente, tipo: TipoTramite) -> list[str]:
    """Why this client cannot file the case online today; empty if they can."""
    if cliente.empresa_id is None:
        return [SOLO_EMPRESAS]
    problemas = problemas_para_contrato(tipo.configuracion.get("marca", ""))
    if not planes_en_portal(tipo.configuracion.get("servicio", "")).exists():
        problemas.append("No hay planes a la venta en el portal.")
    return problemas


@dataclass(frozen=True)
class Eleccion:
    """The choices behind a domicile request, validated."""

    plan: PlanServicio
    sucursal: Oficina
    fecha_inicio: date


def _validar_eleccion(tipo: TipoTramite, datos: dict[str, Any]) -> Eleccion:
    desde, hasta = ventana_fecha_inicio(tipo)
    fecha_inicio = datos["fecha_inicio"]
    if not desde <= fecha_inicio <= hasta:
        raise ValidationError(
            {
                "fecha_inicio": _(
                    "Choose a start date between %(desde)s and %(hasta)s.",
                )
                % {"desde": f"{desde:%d-%m-%Y}", "hasta": f"{hasta:%d-%m-%Y}"},
            },
        )
    plan = (
        planes_en_portal(tipo.configuracion.get("servicio", ""))
        .filter(codigo=datos["plan"])
        .first()
    )
    if plan is None:
        raise ValidationError({"plan": _("This plan is not available.")})
    sucursal = sucursales_activas().filter(pk=datos["sucursal"]).first()
    if sucursal is None or problemas_para_domicilio(sucursal, fecha_inicio):
        raise ValidationError(
            {"sucursal": _("This branch is not available for that date.")},
        )
    return Eleccion(plan, sucursal, fecha_inicio)


def _datos(eleccion: Eleccion) -> dict[str, Any]:
    return {
        "plan": eleccion.plan.codigo,
        "sucursal": eleccion.sucursal.pk,
        "fecha_inicio": eleccion.fecha_inicio.isoformat(),
    }


def _pedir_documento(tramite: Tramite) -> None:
    transaction.on_commit(
        lambda: documento_requerido.send(sender=Tramite, tramite=tramite),
    )


def iniciar_domicilio(
    cliente: Cliente,
    datos: dict[str, Any],
    usuario: User | None = None,
) -> Tramite:
    """File a domicile request from the portal form (HU-24).

    Saves the client's company and signer, records the contract as a draft
    with the plan at the chosen branch, opens the case and asks for its
    document.

    Args:
        cliente: The logged-in client.
        datos: ``empresa``, ``representante``, ``personeria`` (see
            clientes.services.guardar_datos_contratante), ``email_aviso``,
            ``movil_aviso``, ``plan`` (code), ``sucursal`` (id) and
            ``fecha_inicio``.
        usuario: Who filed it.

    Raises:
        TramiteNoDisponibleError: The case cannot be offered online.
        django.core.exceptions.ValidationError: Keyed by the offending field.
        crm_easyoffice.clientes.services.RepresentanteNoDisponibleError: The
            representative's RUT is someone else's record.
    """
    tipo = tipo_domicilio()
    if problemas := no_disponible(cliente, tipo):
        raise TramiteNoDisponibleError(problemas)
    eleccion = _validar_eleccion(tipo, datos)
    marca = marcas_activas().get(nombre=tipo.configuracion["marca"])

    with transaction.atomic():
        representante = guardar_datos_contratante(
            cliente,
            empresa=datos["empresa"],
            representante=datos["representante"],
            personeria=datos["personeria"],
        )
        contrato = crear_contrato(
            cliente=cliente,
            marca=marca,
            lineas=[_linea(eleccion)],
            fecha_inicio=eleccion.fecha_inicio,
            duracion_meses=eleccion.plan.duracion_meses,
            representante=representante,
            email_aviso=datos["email_aviso"],
            movil_aviso=datos["movil_aviso"],
            borrador=True,
        )
        tramite = Tramite.objects.create(
            cliente=cliente,
            tipo=tipo,
            canal=Tramite.Canal.PORTAL,
            datos=_datos(eleccion),
            contrato=contrato,
            creado_por=usuario,
        )
        EventoTramite.objects.create(
            tramite=tramite,
            estado_nuevo=INICIADO,
            usuario=usuario,
        )
        _pedir_documento(tramite)
    # TODO(RF-15): record the case in the audit log (HU-30).
    return tramite


def _linea(eleccion: Eleccion) -> LineaContrato:
    return LineaContrato(
        servicio=eleccion.plan.servicio,
        inmueble=eleccion.sucursal,
        plan=eleccion.plan,
    )


def _venta_pagada(tramite: Tramite) -> bool:
    return tramite.venta is not None and tramite.venta.estado == Venta.Estado.PAGADA


def actualizar_domicilio(
    tramite: Tramite,
    datos: dict[str, Any],
    usuario: User | None = None,
) -> Tramite:
    """Change a request before it is paid; its document is generated again.

    A sale already created for it is cancelled: the client confirms and pays
    the new draft.

    Raises:
        TransicionInvalidaError: The case is paid or completed.
        django.core.exceptions.ValidationError: Keyed by the offending field.
    """
    if (
        _venta_pagada(tramite)
        or (INICIADO, None) not in TRANSICIONES[situacion(tramite)]
    ):
        msg = f"{tramite} can no longer be edited."
        raise TransicionInvalidaError(msg)
    eleccion = _validar_eleccion(tramite.tipo, datos)

    with transaction.atomic():
        if tramite.venta is not None:
            try:
                anular_venta(tramite.venta)
            except VentaNoPagableError:
                msg = f"{tramite}: its sale is no longer pending."
                raise TransicionInvalidaError(msg) from None
        representante = guardar_datos_contratante(
            tramite.cliente,
            empresa=datos["empresa"],
            representante=datos["representante"],
            personeria=datos["personeria"],
        )
        actualizar_borrador(
            tramite.contrato,
            lineas=[_linea(eleccion)],
            fecha_inicio=eleccion.fecha_inicio,
            duracion_meses=eleccion.plan.duracion_meses,
            representante=representante,
            email_aviso=datos["email_aviso"],
            movil_aviso=datos["movil_aviso"],
        )
        Tramite.objects.filter(pk=tramite.pk).update(
            datos=_datos(eleccion),
            venta=None,
        )
        tramite = _mover(tramite, INICIADO, usuario=usuario, detalle="Datos editados.")
        _pedir_documento(tramite)
    return tramite


def cambiar_fecha_inicio(
    tramite: Tramite,
    fecha_inicio: date,
    usuario: User | None = None,
) -> Tramite:
    """Set a new start date after payment, when the chosen one has passed.

    Nothing else changes; the document is generated again with the new date
    and the case returns to the signature step.

    Raises:
        TransicionInvalidaError: The case is not waiting for a new date.
        django.core.exceptions.ValidationError: The date is out of range.
    """
    if situacion(tramite) != (PENDIENTE, FALTA_INFORMACION):
        msg = f"{tramite} is not waiting for a new start date."
        raise TransicionInvalidaError(msg)
    datos = {**tramite.datos, "fecha_inicio": fecha_inicio}
    eleccion = _validar_eleccion(tramite.tipo, datos)
    contrato = tramite.contrato

    with transaction.atomic():
        actualizar_borrador(
            contrato,
            lineas=[_linea(eleccion)],
            fecha_inicio=fecha_inicio,
            duracion_meses=contrato.duracion_meses,
            representante=contrato.representante,
            email_aviso=contrato.email_aviso,
            movil_aviso=contrato.movil_aviso,
        )
        Tramite.objects.filter(pk=tramite.pk).update(datos=_datos(eleccion))
        tramite = _mover(
            tramite,
            INICIADO,
            usuario=usuario,
            detalle="Nueva fecha de inicio.",
        )
        _pedir_documento(tramite)
    return tramite


def fecha_inicio_vencida(tramite: Tramite) -> bool:
    return tramite.contrato.fecha_inicio < timezone.localdate()


def documento_listo(tramite: Tramite) -> Tramite:
    """The document was generated: the client reviews it, or it goes to signing.

    A case already paid (a new start date) skips the review.
    """
    tramite = Tramite.objects.select_related("venta", "contrato").get(pk=tramite.pk)
    if _venta_pagada(tramite):
        return _mover(tramite, PENDIENTE, FIRMA)
    return _mover(tramite, PENDIENTE, REVISION_BORRADOR)


def documento_fallido(tramite: Tramite, detalle: str) -> Tramite:
    """The document could not be generated; the executive sees why."""
    return _mover(tramite, PENDIENTE, FALTA_INFORMACION, detalle=detalle)


def confirmar_borrador(tramite: Tramite, usuario: User | None = None) -> Tramite:
    """The client confirms the draft (RN-13) and is charged for it (RN-40).

    Raises:
        TransicionInvalidaError: The draft is not waiting for review.
        FechaInicioVencidaError: The start date has passed.
        crm_easyoffice.ventas.services.PlanNoDisponibleError: The plan can
            no longer be sold.
    """
    tramite = Tramite.objects.select_related("contrato", "tipo").get(pk=tramite.pk)
    if situacion(tramite) != (PENDIENTE, REVISION_BORRADOR):
        msg = f"{tramite} has no draft waiting for review."
        raise TransicionInvalidaError(msg)
    if fecha_inicio_vencida(tramite):
        raise FechaInicioVencidaError
    if not _requiere(tramite.tipo, "requiere_pago"):
        return _mover(tramite, PENDIENTE, FIRMA, usuario=usuario)

    plan = (
        planes_en_portal(tramite.tipo.configuracion.get("servicio", ""))
        .filter(codigo=tramite.datos["plan"])
        .first()
    )
    if plan is None:
        raise PlanNoDisponibleError
    with transaction.atomic():
        venta = crear_venta(tramite.cliente, lineas_de_plan(plan))
        Tramite.objects.filter(pk=tramite.pk).update(venta=venta)
        return _mover(tramite, PENDIENTE, PAGO, usuario=usuario)


def registrar_pago(venta: Venta) -> Tramite | None:
    """A sale was paid: its case moves to signing, or asks for a new date."""
    tramite = (
        Tramite.objects.select_related("contrato", "motivo").filter(venta=venta).first()
    )
    if tramite is None:
        return None
    if situacion(tramite) != (PENDIENTE, PAGO):
        logger.warning("%s: payment arrived in state %s.", tramite, situacion(tramite))
        return tramite
    if fecha_inicio_vencida(tramite):
        return _mover(tramite, PENDIENTE, FALTA_INFORMACION, detalle=NUEVA_FECHA)
    return _mover(tramite, PENDIENTE, FIRMA)


def verificar_para_firma(tramite: Tramite, usuario: User | None = None) -> None:
    """Check a case may be signed now; if its date has passed, ask for one.

    Raises:
        TransicionInvalidaError: The case is not waiting for a signature.
        FechaInicioVencidaError: The start date has passed; the case now
            waits for a new one.
    """
    tramite = Tramite.objects.select_related("contrato", "motivo").get(pk=tramite.pk)
    if situacion(tramite) != (PENDIENTE, FIRMA):
        msg = f"{tramite} is not waiting for a signature."
        raise TransicionInvalidaError(msg)
    if fecha_inicio_vencida(tramite):
        _mover(
            tramite,
            PENDIENTE,
            FALTA_INFORMACION,
            detalle=NUEVA_FECHA,
            usuario=usuario,
        )
        raise FechaInicioVencidaError


def completar(tramite: Tramite, usuario: User | None = None) -> Tramite:
    """Every signature is in (RN-24): the case ends and its contract is in force."""
    with transaction.atomic():
        tramite = _mover(tramite, COMPLETADO, usuario=usuario)
        if tramite.contrato is not None:
            activar_contrato(tramite.contrato)
    return tramite


NO_DISPONIBLE = (
    "El trámite en línea no está disponible por ahora. Escríbenos y te ayudamos "
    "a contratarlo."
)


def formulario_domicilio(cliente: Cliente) -> dict[str, Any]:
    """What the portal form needs: availability, choices and the pre-fill.

    The pre-fill comes only from the client's own records; a field they have
    never filled is blank. Branches and the reason a case is unavailable are
    computed for today; the request is checked again for its start date.
    """
    tipo = tipo_domicilio()
    desde, hasta = ventana_fecha_inicio(tipo)
    problemas = no_disponible(cliente, tipo)
    sucursales = sucursales_para_domicilio(desde) if not problemas else []
    if not problemas and not sucursales:
        problemas = ["Ninguna sucursal tiene completos los datos del contrato."]

    motivo = ""
    if cliente.empresa_id is None:
        motivo = problemas[0]
    elif problemas:
        logger.warning("Online domicile unavailable: %s", "; ".join(problemas))
        motivo = NO_DISPONIBLE

    prefill = datos_contratante(cliente) if cliente.empresa_id else None
    email, movil = contacto_de_aviso(cliente)
    return {
        "disponible": not problemas,
        "motivo_no_disponible": motivo,
        "fecha_min": desde,
        "fecha_max": hasta,
        "planes": (
            list(planes_en_portal(tipo.configuracion.get("servicio", "")))
            if not problemas
            else []
        ),
        "sucursales": sucursales,
        "datos": (
            {**prefill, "contacto": {"email_aviso": email, "movil_aviso": movil}}
            if prefill
            else None
        ),
    }


def reintentar_documento(tramite: Tramite, usuario: User | None = None) -> Tramite:
    """Generate the document again once the executive completed the data.

    Raises:
        TransicionInvalidaError: The case is not waiting for information, or
            it waits for the client's new start date.
    """
    if situacion(tramite) != (PENDIENTE, FALTA_INFORMACION) or (
        tramite.detalle_pendiente == NUEVA_FECHA
    ):
        msg = f"{tramite} is not waiting for data the executive can complete."
        raise TransicionInvalidaError(msg)
    with transaction.atomic():
        tramite = _mover(
            tramite,
            INICIADO,
            usuario=usuario,
            detalle="Documento solicitado de nuevo.",
        )
        _pedir_documento(tramite)
    return tramite


def _con_situacion_a(fecha: date) -> QuerySet[Tramite]:
    """Cases annotated with their state and reason at the end of ``fecha``.

    Read from the append-only history: the latest move on or before that
    day, in local time. A case opened later has neither.
    """
    ultimo = EventoTramite.objects.filter(
        tramite=OuterRef("pk"),
        fecha__date__lte=fecha,
    ).order_by("-fecha", "-pk")
    return Tramite.objects.annotate(
        estado_a=Subquery(ultimo.values("estado_nuevo")[:1]),
        motivo_a=Subquery(ultimo.values("motivo_nuevo")[:1]),
    )


def pendientes_por_motivo(fecha: date) -> list[dict[str, Any]]:
    """Cases pending at the end of ``fecha``, per reason, most cases first (RF-47).

    Returns:
        One ``{motivo, nombre, cantidad}`` per reason with pending cases.
    """
    filas = list(
        _con_situacion_a(fecha)
        .filter(estado_a=PENDIENTE)
        .values("motivo_a")
        .annotate(cantidad=Count("pk"))
        .order_by("-cantidad", "motivo_a"),
    )
    nombres = dict(
        MotivoPendiente.objects.filter(
            codigo__in=[fila["motivo_a"] for fila in filas],
        ).values_list("codigo", "nombre"),
    )
    return [
        {
            "motivo": fila["motivo_a"],
            "nombre": nombres.get(fila["motivo_a"], fila["motivo_a"]),
            "cantidad": fila["cantidad"],
        }
        for fila in filas
    ]


def en_firma(fecha: date) -> QuerySet[Tramite]:
    """Cases waiting for a signature at the end of ``fecha``.

    A case reaches this step only once its document exists: after the
    client confirms the draft and, when the type requires it, pays.
    """
    return _con_situacion_a(fecha).filter(estado_a=PENDIENTE, motivo_a=FIRMA)


def ventas_por_ejecutivo(ventas: QuerySet[Venta]) -> list[dict[str, Any]]:
    """Amount and number of sales per executive, largest amount first (RF-14).

    The executive is the one responsible for the contract of the sale's
    case, else the staff member who opened the case. A sale with neither
    (bought in the portal, or with no case) has ``ejecutivo`` None. Sales
    are linked to contracts only through their case (MD-10).

    ASSUMPTION: pending validation with Easy Office. Who an online sale
    belongs to is not defined; portal contracts have no executive yet.
    """
    abierto_por_staff = Q(
        creado_por__isnull=False,
        creado_por__cuenta_cliente__isnull=True,
    )
    responsable = (
        Tramite.objects.filter(venta=OuterRef("pk"))
        .order_by("pk")
        .annotate(
            responsable=Coalesce(
                "contrato__ejecutivo_responsable_id",
                Case(When(abierto_por_staff, then="creado_por_id")),
            ),
        )
        .values("responsable")[:1]
    )
    filas = list(
        ventas.annotate(ejecutivo_id=Subquery(responsable))
        .values("ejecutivo_id")
        .annotate(monto=Sum("total"), cantidad=Count("pk"))
        .order_by("-monto", "ejecutivo_id"),
    )
    nombres = {
        pk: nombre or email
        for pk, nombre, email in get_user_model()
        .objects.filter(pk__in=[fila["ejecutivo_id"] for fila in filas])
        .values_list("pk", "name", "email")
    }
    return [
        {
            "ejecutivo": nombres.get(fila["ejecutivo_id"]),
            "monto": int(fila["monto"]),
            "cantidad": fila["cantidad"],
        }
        for fila in filas
    ]
