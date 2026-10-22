"""Case state changes and the request flows (HU-24). The only writer of cases.

Every move goes through ``_mover``, which checks ``TRANSICIONES`` and writes
an EventoTramite. A state is (estado, motivo); RN-42 keeps the reason only
while the case is pending.

Two case types run on these functions: the domicile (PLT-01, sold in the
portal) and the warehouse (PLT-02, started by an executive). They read the
case type's configuration, never its name; what differs between them is
listed in docs/variation-points.md.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from datetime import timedelta
from decimal import Decimal
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
from crm_easyoffice.contratos.services import calcular_vencimiento
from crm_easyoffice.contratos.services import contacto_de_aviso
from crm_easyoffice.contratos.services import crear_contrato
from crm_easyoffice.contratos.services import duraciones_activas
from crm_easyoffice.contratos.services import inmuebles_ocupados
from crm_easyoffice.inmuebles.services import inmueble_de
from crm_easyoffice.inmuebles.services import inmuebles_para
from crm_easyoffice.inmuebles.services import problemas_inmueble
from crm_easyoffice.ventas.models import Venta
from crm_easyoffice.ventas.services import PlanNoDisponibleError
from crm_easyoffice.ventas.services import VentaNoPagableError
from crm_easyoffice.ventas.services import anular_venta
from crm_easyoffice.ventas.services import ciclos_pago_activos
from crm_easyoffice.ventas.services import crear_venta
from crm_easyoffice.ventas.services import lineas_de_plan
from crm_easyoffice.ventas.services import planes_en_portal
from crm_easyoffice.ventas.services import servicios_contratables

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
    from crm_easyoffice.ventas.models import Servicio

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
    "El trámite «{nombre}» en línea es para empresas. Escríbenos y te ayudamos "
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


def tipo_tramite(codigo: str) -> TipoTramite:
    return TipoTramite.objects.get(codigo=codigo)


def tipo_domicilio() -> TipoTramite:
    return tipo_tramite(TIPO_DOMICILIO)


def canales(tipo: TipoTramite) -> list[str]:
    """Where a case of this type may be started (``canales``)."""
    return list(tipo.configuracion.get("canales", []))


def tipos_iniciables(canal: str) -> QuerySet[TipoTramite]:
    """Active case types a case may be started for through ``canal``."""
    return TipoTramite.objects.filter(
        activo=True,
        configuracion__canales__contains=[canal],
    )


def ventana_fecha_inicio(
    tipo: TipoTramite,
    hoy: date | None = None,
) -> tuple[date, date]:
    """First and last start date the client may choose: today … +N days.

    ASSUMPTION: pending validation with Easy Office. N defaults to 30.
    """
    hoy = hoy or timezone.localdate()
    return hoy, hoy + timedelta(days=tipo.configuracion.get("inicio_max_dias", 30))


def _requiere(tramite: Tramite, paso: str) -> bool:
    """Whether the case goes through ``paso`` (requiere_pago, requiere_firma).

    The value is true or false, or the channels whose cases need the step:
    the bodega is paid online only when the client files it in the portal.
    """
    valor = tramite.tipo.configuracion.get(paso, True)
    if isinstance(valor, list):
        return tramite.canal in valor
    return bool(valor)


def _con_planes(tipo: TipoTramite) -> bool:
    return bool(tipo.configuracion.get("planes", False))


def _lineas_config(tipo: TipoTramite) -> list[dict[str, Any]]:
    return list(tipo.configuracion.get("lineas", []))


def _tipo_cliente(cliente: Cliente) -> str:
    return "persona" if cliente.empresa_id is None else "empresa"


def cliente_admitido(cliente: Cliente, tipo: TipoTramite) -> bool:
    """Whether the case type is for this kind of client (``tipos_cliente``)."""
    return _tipo_cliente(cliente) in tipo.configuracion.get("tipos_cliente", [])


def _servicios_de(tipo: TipoTramite) -> dict[str, Servicio]:
    codigos = [linea["servicio"] for linea in _lineas_config(tipo)]
    return {s.codigo: s for s in servicios_contratables().filter(codigo__in=codigos)}


def no_disponible(
    cliente: Cliente,
    tipo: TipoTramite,
    canal: str = Tramite.Canal.PORTAL,
) -> list[str]:
    """Why this client cannot file the case today through ``canal``.

    Empty if they can. The messages are for staff, except the one a portal
    client reads when the type is not for them (SOLO_EMPRESAS).
    """
    if not cliente_admitido(cliente, tipo):
        if canal == Tramite.Canal.PORTAL:
            return [SOLO_EMPRESAS.format(nombre=tipo.nombre)]
        return [f"«{tipo.nombre}» no es para este tipo de cliente."]
    problemas = problemas_para_contrato(tipo.configuracion.get("marca", ""))
    if (
        _con_planes(tipo)
        and not planes_en_portal(
            tipo.configuracion.get("servicio", ""),
        ).exists()
    ):
        problemas.append("No hay planes a la venta en el portal.")
    lineas = _lineas_config(tipo)
    if not lineas:
        problemas.append("La configuración del trámite no define sus servicios.")
    servicios = _servicios_de(tipo)
    problemas += [
        f"El servicio {linea['servicio']!r} no existe o está inactivo."
        for linea in lineas
        if linea["servicio"] not in servicios
    ]
    return problemas


@dataclass(frozen=True)
class Eleccion:
    """The choices behind a request, validated: what its contract will hold.

    ``plan`` is set for a type sold by plans; ``inmuebles`` maps each line's
    property role (``sucursal``, ``bodega``) to the chosen property.
    """

    plan: PlanServicio | None
    inmuebles: dict[str, Oficina]
    fecha_inicio: date
    duracion_meses: int
    lineas: list[LineaContrato]


NO_DISPONIBLE_EN_FECHA = {
    "sucursal": _("This branch is not available for that date."),
    "bodega": _("This warehouse is not available for that date."),
}


def _no_disponible_en(rol: str) -> str:
    return NO_DISPONIBLE_EN_FECHA.get(
        rol,
        _("This property is not available for that date."),
    )


def _ocupado(
    linea: dict[str, Any],
    inmueble: Oficina,
    desde: date,
    hasta: date,
    contrato_id: int | None,
) -> bool:
    if not linea.get("inmueble_exclusivo", False):
        return False
    ocupados = inmuebles_ocupados(
        [inmueble.pk],
        desde,
        hasta,
        excluir_contrato=contrato_id,
    )
    return inmueble.pk in ocupados


def _validar_eleccion(
    tipo: TipoTramite,
    datos: dict[str, Any],
    contrato_id: int | None = None,
) -> Eleccion:
    """Check the request's choices against the type's configuration.

    Raises:
        django.core.exceptions.ValidationError: Keyed by the offending field:
            ``fecha_inicio``, ``plan``, a property role, ``lineas``.
    """
    desde, hasta = ventana_fecha_inicio(tipo)
    fecha_inicio = datos["fecha_inicio"]
    if isinstance(fecha_inicio, str):
        fecha_inicio = date.fromisoformat(fecha_inicio)
    if not desde <= fecha_inicio <= hasta:
        raise ValidationError(
            {
                "fecha_inicio": _(
                    "Choose a start date between %(desde)s and %(hasta)s.",
                )
                % {"desde": f"{desde:%d-%m-%Y}", "hasta": f"{hasta:%d-%m-%Y}"},
            },
        )
    plan = None
    if _con_planes(tipo):
        plan = (
            planes_en_portal(tipo.configuracion.get("servicio", ""))
            .filter(codigo=datos.get("plan", ""))
            .first()
        )
        if plan is None:
            raise ValidationError({"plan": _("This plan is not available.")})
        duracion = plan.duracion_meses
    else:
        duracion = int(
            datos.get("duracion_meses")
            or tipo.configuracion.get("duracion_por_defecto", 12),
        )
    vencimiento = calcular_vencimiento(fecha_inicio, duracion)

    inmuebles: dict[str, Oficina] = {}
    errores: dict[str, str] = {}
    for linea in _lineas_config(tipo):
        rol = linea["inmueble"]
        inmueble = inmueble_de(rol, datos[rol]) if datos.get(rol) else None
        if (
            inmueble is None
            or problemas_inmueble(inmueble, fecha_inicio, linea["requisitos"])
            or _ocupado(linea, inmueble, fecha_inicio, vencimiento, contrato_id)
        ):
            errores[rol] = _no_disponible_en(rol)
        else:
            inmuebles[rol] = inmueble
    if errores:
        raise ValidationError(errores)

    return Eleccion(
        plan=plan,
        inmuebles=inmuebles,
        fecha_inicio=fecha_inicio,
        duracion_meses=duracion,
        lineas=_lineas(tipo, plan, inmuebles, datos.get("lineas", [])),
    )


def _lineas(
    tipo: TipoTramite,
    plan: PlanServicio | None,
    inmuebles: dict[str, Oficina],
    elegidas: list[dict[str, Any]],
) -> list[LineaContrato]:
    """The contract's lines in the configured order.

    The plan's service takes the plan (price, cycle, duration); a line
    configured ``incluido_en_plan`` is paid by it (copied at 0, with the
    plan's cycle); any other line takes the cycle chosen for it, or its
    service's default, and the agreed price when its service has no list
    price (contratos checks RN-44).
    """
    servicios = _servicios_de(tipo)
    ciclos = {ciclo.codigo: ciclo for ciclo in ciclos_pago_activos()}
    por_servicio = {elegida["servicio"]: elegida for elegida in elegidas}
    lineas = []
    for linea in _lineas_config(tipo):
        servicio = servicios[linea["servicio"]]
        inmueble = inmuebles[linea["inmueble"]]
        if plan is not None and plan.servicio_id == servicio.pk:
            lineas.append(
                LineaContrato(servicio=servicio, inmueble=inmueble, plan=plan),
            )
            continue
        if plan is not None and linea.get("incluido_en_plan", False):
            lineas.append(
                LineaContrato(servicio=servicio, inmueble=inmueble, incluido_en=plan),
            )
            continue
        elegida = por_servicio.get(servicio.codigo, {})
        codigo_ciclo = elegida.get("ciclo_pago")
        if codigo_ciclo and codigo_ciclo not in ciclos:
            raise ValidationError({"lineas": _("Unknown payment cycle.")})
        precio = elegida.get("precio")
        lineas.append(
            LineaContrato(
                servicio=servicio,
                inmueble=inmueble,
                ciclo_pago=ciclos.get(codigo_ciclo) if codigo_ciclo else None,
                precio=Decimal(str(precio)) if precio not in (None, "") else None,
            ),
        )
    return lineas


def _datos(eleccion: Eleccion) -> dict[str, Any]:
    """The choices kept on the case: plan or term, properties, start date."""
    datos: dict[str, Any] = {}
    if eleccion.plan is not None:
        datos["plan"] = eleccion.plan.codigo
    datos |= {rol: inmueble.pk for rol, inmueble in eleccion.inmuebles.items()}
    datos["fecha_inicio"] = eleccion.fecha_inicio.isoformat()
    if eleccion.plan is None:
        datos["duracion_meses"] = eleccion.duracion_meses
        datos["lineas"] = [
            {
                "servicio": linea.servicio.codigo,
                "ciclo_pago": linea.ciclo_pago.codigo if linea.ciclo_pago else None,
                "precio": str(linea.precio) if linea.precio is not None else None,
            }
            for linea in eleccion.lineas
        ]
    return datos


def _pedir_documento(tramite: Tramite) -> None:
    transaction.on_commit(
        lambda: documento_requerido.send(sender=Tramite, tramite=tramite),
    )


def _exigir_canal(tramite: Tramite, canal: str) -> None:
    """Each side acts only on its own cases: the client on portal ones."""
    if tramite.canal != canal:
        msg = f"{tramite} belongs to the {tramite.canal} channel."
        raise TransicionInvalidaError(msg)


def iniciar_tramite(
    tipo: TipoTramite,
    cliente: Cliente,
    datos: dict[str, Any],
    *,
    canal: str,
    usuario: User | None = None,
) -> Tramite:
    """File a request: the client's data, its draft contract, the case (HU-24).

    Saves the client's company and signer, records the contract as a draft
    with the type's lines at the chosen properties, opens the case and asks
    for its document.

    Args:
        tipo: The case type; its ``canal`` must be ``canal``.
        cliente: The client the case is for.
        datos: ``empresa``, ``representante``, ``personeria`` (see
            clientes.services.guardar_datos_contratante), ``email_aviso``,
            ``movil_aviso``, ``fecha_inicio``, one property id per line role
            (``sucursal``, ``bodega``), and ``plan`` or ``duracion_meses``
            and ``lineas`` (``servicio``, ``ciclo_pago``, ``precio``).
        canal: Where it is filed: the portal (the client) or the backoffice
            (an executive, who becomes the contract's executive).
        usuario: Who filed it.

    Raises:
        TramiteNoDisponibleError: The case cannot be offered.
        django.core.exceptions.ValidationError: Keyed by the offending field.
        crm_easyoffice.clientes.services.RepresentanteNoDisponibleError: The
            representative's RUT is someone else's record.
    """
    if problemas := no_disponible(cliente, tipo, canal):
        raise TramiteNoDisponibleError(problemas)
    if canal not in canales(tipo):
        raise TramiteNoDisponibleError([f"«{tipo.nombre}» no se inicia por {canal}."])
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
            lineas=eleccion.lineas,
            fecha_inicio=eleccion.fecha_inicio,
            duracion_meses=eleccion.duracion_meses,
            representante=representante,
            email_aviso=datos["email_aviso"],
            movil_aviso=datos["movil_aviso"],
            ejecutivo=usuario if canal == Tramite.Canal.BACKOFFICE else None,
            borrador=True,
        )
        tramite = Tramite.objects.create(
            cliente=cliente,
            tipo=tipo,
            canal=canal,
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


def iniciar_domicilio(
    cliente: Cliente,
    datos: dict[str, Any],
    usuario: User | None = None,
) -> Tramite:
    """File a domicile request from the portal form (HU-24).

    See ``iniciar_tramite``; ``datos`` carries ``plan`` and ``sucursal``.
    """
    return iniciar_tramite(
        tipo_domicilio(),
        cliente,
        datos,
        canal=Tramite.Canal.PORTAL,
        usuario=usuario,
    )


def _venta_pagada(tramite: Tramite) -> bool:
    return tramite.venta is not None and tramite.venta.estado == Venta.Estado.PAGADA


def actualizar_tramite(
    tramite: Tramite,
    datos: dict[str, Any],
    usuario: User | None = None,
    *,
    canal: str = Tramite.Canal.PORTAL,
) -> Tramite:
    """Change a request before it is paid; its document is generated again.

    A sale already created for it is cancelled: the client confirms and pays
    the new draft.

    Raises:
        TransicionInvalidaError: The case is paid or completed, or belongs
            to the other channel.
        django.core.exceptions.ValidationError: Keyed by the offending field.
    """
    _exigir_canal(tramite, canal)
    if (
        _venta_pagada(tramite)
        or (INICIADO, None) not in TRANSICIONES[situacion(tramite)]
    ):
        msg = f"{tramite} can no longer be edited."
        raise TransicionInvalidaError(msg)
    eleccion = _validar_eleccion(tramite.tipo, datos, tramite.contrato_id)

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
            lineas=eleccion.lineas,
            fecha_inicio=eleccion.fecha_inicio,
            duracion_meses=eleccion.duracion_meses,
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


# The portal's name for it (HU-24).
actualizar_domicilio = actualizar_tramite


def cambiar_fecha_inicio(
    tramite: Tramite,
    fecha_inicio: date,
    usuario: User | None = None,
    *,
    canal: str = Tramite.Canal.PORTAL,
) -> Tramite:
    """Set a new start date after payment, when the chosen one has passed.

    Nothing else changes; the document is generated again with the new date
    and the case returns to the signature step.

    Raises:
        TransicionInvalidaError: The case is not waiting for a new date, or
            belongs to the other channel.
        django.core.exceptions.ValidationError: The date is out of range.
    """
    _exigir_canal(tramite, canal)
    if situacion(tramite) != (PENDIENTE, FALTA_INFORMACION):
        msg = f"{tramite} is not waiting for a new start date."
        raise TransicionInvalidaError(msg)
    datos = {**tramite.datos, "fecha_inicio": fecha_inicio}
    eleccion = _validar_eleccion(tramite.tipo, datos, tramite.contrato_id)
    contrato = tramite.contrato

    with transaction.atomic():
        actualizar_borrador(
            contrato,
            lineas=eleccion.lineas,
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


CONFIRMADO_POR_EJECUTIVO = "El ejecutivo registró la confirmación del cliente."


def confirmar_borrador(
    tramite: Tramite,
    usuario: User | None = None,
    *,
    canal: str = Tramite.Canal.PORTAL,
) -> Tramite:
    """The client confirms the draft (RN-13) and is charged for it (RN-40).

    In the backoffice the executive records the client's confirmation.

    ASSUMPTION: pending validation with Easy Office. For a backoffice case
    the client reviews the draft with the executive, outside the platform.

    Raises:
        TransicionInvalidaError: The draft is not waiting for review, or the
            case belongs to the other channel.
        FechaInicioVencidaError: The start date has passed.
        crm_easyoffice.ventas.services.PlanNoDisponibleError: The plan can
            no longer be sold.
    """
    tramite = Tramite.objects.select_related("contrato", "tipo").get(pk=tramite.pk)
    _exigir_canal(tramite, canal)
    if situacion(tramite) != (PENDIENTE, REVISION_BORRADOR):
        msg = f"{tramite} has no draft waiting for review."
        raise TransicionInvalidaError(msg)
    if fecha_inicio_vencida(tramite):
        raise FechaInicioVencidaError
    detalle = CONFIRMADO_POR_EJECUTIVO if canal == Tramite.Canal.BACKOFFICE else ""
    if not _requiere(tramite, "requiere_pago"):
        return _mover(tramite, PENDIENTE, FIRMA, usuario=usuario, detalle=detalle)

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
        return _mover(tramite, PENDIENTE, PAGO, usuario=usuario, detalle=detalle)


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


def _disponibles(
    linea: dict[str, Any],
    desde: date,
) -> list[Oficina]:
    """The properties a line may take for a start on ``desde``.

    An exclusive property already held that day is left out; the request is
    checked again for its whole term.
    """
    inmuebles = inmuebles_para(linea["inmueble"], desde, linea["requisitos"])
    if not linea.get("inmueble_exclusivo", False):
        return inmuebles
    ocupados = inmuebles_ocupados([i.pk for i in inmuebles], desde, desde)
    return [i for i in inmuebles if i.pk not in ocupados]


def formulario_tramite(
    tipo: TipoTramite,
    cliente: Cliente,
    canal: str = Tramite.Canal.BACKOFFICE,
) -> dict[str, Any]:
    """What a request form needs: availability, choices and the pre-fill.

    The pre-fill comes only from the client's own records; a field they have
    never filled is blank. Properties and problems are computed for today;
    the request is checked again for its start date. ``problemas`` is for
    staff; ``formulario_portal`` turns it into the client's reason.
    """
    desde, hasta = ventana_fecha_inicio(tipo)
    problemas = no_disponible(cliente, tipo, canal)
    if canal not in canales(tipo):
        problemas.append(f"«{tipo.nombre}» no se inicia por {canal}.")
    inmuebles: dict[str, list[Oficina]] = {}
    if not problemas:
        for linea in _lineas_config(tipo):
            inmuebles[linea["inmueble"]] = _disponibles(linea, desde)
            if not inmuebles[linea["inmueble"]]:
                problemas.append(
                    f"Ningún inmueble para «{linea['inmueble']}» tiene completos "
                    "los datos del contrato.",
                )
    servicios = _servicios_de(tipo) if not problemas else {}

    prefill = datos_contratante(cliente) if cliente.empresa_id else None
    email, movil = contacto_de_aviso(cliente)
    return {
        "disponible": not problemas,
        "problemas": problemas,
        "fecha_min": desde,
        "fecha_max": hasta,
        "planes": (
            list(planes_en_portal(tipo.configuracion.get("servicio", "")))
            if not problemas and _con_planes(tipo)
            else []
        ),
        "duraciones": (
            duraciones_activas() if not problemas and not _con_planes(tipo) else []
        ),
        "duracion_por_defecto": tipo.configuracion.get("duracion_por_defecto"),
        "inmuebles": inmuebles,
        "lineas": [
            {"servicio": servicios[linea["servicio"]], "inmueble": linea["inmueble"]}
            for linea in _lineas_config(tipo)
            if linea["servicio"] in servicios
        ],
        "ciclos_pago": list(ciclos_pago_activos()) if not problemas else [],
        "datos": (
            {**prefill, "contacto": {"email_aviso": email, "movil_aviso": movil}}
            if prefill
            else None
        ),
    }


def formulario_portal(tipo: TipoTramite, cliente: Cliente) -> dict[str, Any]:
    """What a portal request form needs; see formulario_tramite.

    The client reads a plain reason, never the staff detail.
    """
    formulario = formulario_tramite(tipo, cliente, Tramite.Canal.PORTAL)
    problemas = formulario.pop("problemas")
    motivo = ""
    if not cliente_admitido(cliente, tipo):
        motivo = problemas[0]
    elif problemas:
        logger.warning("Online %s unavailable: %s", tipo.codigo, "; ".join(problemas))
        motivo = NO_DISPONIBLE
    return {**formulario, "nombre": tipo.nombre, "motivo_no_disponible": motivo}


def formulario_domicilio(cliente: Cliente) -> dict[str, Any]:
    """What the portal's domicile form needs (HU-24); see formulario_portal."""
    formulario = formulario_portal(tipo_domicilio(), cliente)
    return {
        "disponible": formulario["disponible"],
        "motivo_no_disponible": formulario["motivo_no_disponible"],
        "fecha_min": formulario["fecha_min"],
        "fecha_max": formulario["fecha_max"],
        "planes": formulario["planes"],
        "sucursales": formulario["inmuebles"].get("sucursal", []),
        "datos": formulario["datos"],
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
