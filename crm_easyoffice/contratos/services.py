"""Creating contracts and reading who occupies a property (HU-60)."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count
from django.db.models import Exists
from django.db.models import OuterRef
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _

from crm_easyoffice.clientes.services import representa_a
from crm_easyoffice.configuracion.services import ConfiguracionIncompletaError
from crm_easyoffice.configuracion.services import cuenta_pago_para
from crm_easyoffice.configuracion.services import cuentas_pago_activas
from crm_easyoffice.configuracion.services import marcas_activas
from crm_easyoffice.inmuebles.services import sucursales_activas
from crm_easyoffice.ventas.services import ciclos_pago_activos
from crm_easyoffice.ventas.services import servicios_contratables

from .folio import formatear_folio
from .folio import siguiente_correlativo
from .models import Contrato
from .models import DuracionContrato
from .models import ServicioContratado

if TYPE_CHECKING:
    from collections.abc import Sequence
    from decimal import Decimal

    from django.db.models import QuerySet

    from crm_easyoffice.clientes.models import Cliente
    from crm_easyoffice.clientes.models import RepresentanteLegal
    from crm_easyoffice.configuracion.models import CuentaPago
    from crm_easyoffice.configuracion.models import Marca
    from crm_easyoffice.inmuebles.models import Oficina
    from crm_easyoffice.users.models import User
    from crm_easyoffice.ventas.models import CicloPago
    from crm_easyoffice.ventas.models import PlanServicio
    from crm_easyoffice.ventas.models import Servicio


@dataclass(frozen=True)
class LineaContrato:
    """A service to contract, as the executive or the client chose it.

    ``ciclo_pago`` defaults to the service's cycle. ``precio`` is given only
    for a service without a fixed price; otherwise the list price is copied.
    A ``plan`` (portal) sets both the price and the cycle.
    """

    servicio: Servicio
    ciclo_pago: CicloPago | None = None
    inmueble: Oficina | None = None
    precio: Decimal | None = None
    plan: PlanServicio | None = None


class ContratoNoEditableError(Exception):
    """Only a draft contract can be changed, activated or annulled this way."""


def calcular_vencimiento(inicio: date, meses: int) -> date:
    """Expiry: start plus ``meses`` months minus one day (RN-37).

    2026-10-02 for 12 months expires on 2027-10-01.

    ASSUMPTION: pending validation with Easy Office. When the start day does
    not exist in the target month (31 January plus one month), the contract
    expires on that month's last day, so the term never runs short.
    """
    total = inicio.month - 1 + meses
    anio, mes = inicio.year + total // 12, total % 12 + 1
    ultimo_dia = calendar.monthrange(anio, mes)[1]
    if inicio.day > ultimo_dia:
        return date(anio, mes, ultimo_dia)
    return date(anio, mes, inicio.day) - timedelta(days=1)


def _codigo_sucursal(lineas: Sequence[LineaContrato], explicito: str | None) -> str:
    """The folio's branch code: from the first located service, else explicit.

    ASSUMPTION: pending validation with Easy Office. A contract with no
    located service, or whose first located property is a warehouse, takes
    the branch the executive names; which branch numbers such contracts is
    not confirmed.
    """
    ubicada = next((linea for linea in lineas if linea.inmueble is not None), None)
    derivado = ubicada.inmueble.codigo_sucursal if ubicada else None
    if derivado:
        if explicito and explicito != derivado:
            mensaje = _("The first located service sets the branch: %(codigo)s.")
            raise ValidationError({"codigo_sucursal": mensaje % {"codigo": derivado}})
        return derivado

    if not explicito:
        raise ValidationError(
            {
                "codigo_sucursal": ValidationError(
                    _("Name the branch: no located service gives one."),
                    code="sucursal_no_determinada",
                ),
            },
        )
    codigos = set(sucursales_activas().values_list("codigo_sucursal", flat=True))
    if explicito not in codigos:
        raise ValidationError({"codigo_sucursal": _("Unknown or inactive branch.")})
    return explicito


def _servicios(lineas: Sequence[LineaContrato]) -> list[ServicioContratado]:
    """Validate the lines and copy what each contracted service keeps."""
    if not lineas:
        raise ValidationError(
            {"servicios": _("A contract needs at least one service.")},
        )
    codigos = [linea.servicio.codigo for linea in lineas]
    if len(codigos) != len(set(codigos)):
        raise ValidationError({"servicios": _("Each service may appear only once.")})

    copiados = []
    for orden, linea in enumerate(lineas, start=1):
        servicio = linea.servicio
        if not servicio.activo:
            raise ValidationError(
                {
                    "servicios": _("%(servicio)s is not active.")
                    % {"servicio": servicio},
                },
            )
        if linea.plan is not None:
            _validar_plan(linea)
            ciclo = linea.plan.ciclo_pago
        else:
            ciclo = linea.ciclo_pago or servicio.ciclo_pago_default
        if ciclo is None:
            raise ValidationError(
                {
                    "servicios": _("Choose a payment cycle for %(servicio)s.")
                    % {"servicio": servicio},
                },
            )
        if linea.inmueble is not None and not linea.inmueble.activa:
            raise ValidationError({"servicios": _("The property is not active.")})
        copiados.append(
            ServicioContratado(
                orden=orden,
                servicio=servicio,
                nombre=servicio.nombre,
                descripcion=servicio.descripcion,
                precio=(
                    linea.plan.precio
                    if linea.plan is not None
                    else _precio(servicio, linea.precio)
                ),
                precio_incluye_iva=(
                    linea.plan.precio_incluye_iva
                    if linea.plan is not None
                    else servicio.precio_incluye_iva
                ),
                ciclo_pago=ciclo,
                inmueble=linea.inmueble,
            ),
        )
    return copiados


def _validar_plan(linea: LineaContrato) -> None:
    """A plan sets price and cycle; it must be its service's, and not combined.

    RN-44 still holds: a plan's price is a list price, the same for everyone.
    """
    plan = linea.plan
    if plan.servicio_id != linea.servicio.pk:
        raise ValidationError({"servicios": _("The plan belongs to another service.")})
    if not plan.activo:
        raise ValidationError({"servicios": _("The plan is not active.")})
    if linea.precio is not None or linea.ciclo_pago is not None:
        raise ValidationError(
            {"servicios": _("A plan sets its own price and payment cycle.")},
        )


def _validar_duracion_de_planes(lineas: Sequence[LineaContrato], meses: int) -> None:
    if any(linea.plan and linea.plan.duracion_meses != meses for linea in lineas):
        raise ValidationError(
            {"duracion_meses": _("The duration must be the plan's.")},
        )


def _precio(servicio: Servicio, acordado: Decimal | None) -> Decimal:
    """The list price, or the agreed one for a service without a fixed price.

    RN-44: there are no special prices per client, so a fixed price cannot
    be overridden.
    """
    if servicio.precio_base is not None:
        if acordado is not None and acordado != servicio.precio_base:
            raise ValidationError(
                {
                    "servicios": _("%(servicio)s has a fixed price.")
                    % {"servicio": servicio},
                },
            )
        return servicio.precio_base
    if acordado is None:
        raise ValidationError(
            {
                "servicios": _("%(servicio)s has no fixed price; give the agreed one.")
                % {"servicio": servicio},
            },
        )
    return acordado


def crear_contrato(  # noqa: PLR0913 - mirrors the contract form
    *,
    cliente: Cliente,
    marca: Marca,
    lineas: Sequence[LineaContrato],
    fecha_inicio: date,
    duracion_meses: int,
    cuenta_pago: CuentaPago | None = None,
    representante: RepresentanteLegal | None = None,
    codigo_sucursal: str | None = None,
    email_aviso: str = "",
    movil_aviso: str = "",
    ejecutivo: User | None = None,
    renovacion_automatica: bool = True,
    dias_aviso_termino: int = 30,
    fecha_emision: date | None = None,
    borrador: bool = False,
) -> Contrato:
    """Record a contract with its services and give it the next folio.

    ``borrador`` records a portal request that is not in force until its
    case is signed (see ``activar_contrato``).

    Args:
        cliente: The contracting client, a person or a company.
        marca: Brand the contract is issued under.
        lineas: The services, in the order the contract lists them.
        fecha_inicio: Start of the term.
        duracion_meses: Term, one of the active DuracionContrato values.
        cuenta_pago: Account to pay into; the brand's default when omitted.
        representante: Who signs for a company client.
        codigo_sucursal: Branch for the folio, only when no located service
            gives one.
        email_aviso: Email for notices.
        movil_aviso: Mobile for notices.
        ejecutivo: Executive in charge.
        renovacion_automatica: Renews for the same term unless terminated.
        dias_aviso_termino: Notice before expiry to terminate.
        fecha_emision: Day of issue, whose year numbers the folio; today when
            omitted.

    Raises:
        django.core.exceptions.ValidationError: Keyed by the offending field.
    """
    if not marca.activa:
        raise ValidationError({"marca": _("The brand is not active.")})
    if not DuracionContrato.objects.filter(meses=duracion_meses, activa=True).exists():
        raise ValidationError({"duracion_meses": _("Not an offered duration.")})
    try:
        cuenta = cuenta_pago_para(marca, cuenta_pago)
    except ConfiguracionIncompletaError as error:
        raise ValidationError({"cuenta_pago": str(error)}) from error
    _validar_representante(cliente, representante, fecha_inicio)
    _validar_duracion_de_planes(lineas, duracion_meses)
    servicios = _servicios(lineas)
    codigo = _codigo_sucursal(lineas, codigo_sucursal)
    anio = (fecha_emision or timezone.localdate()).year

    with transaction.atomic():
        correlativo = siguiente_correlativo(anio)
        contrato = Contrato(
            folio=formatear_folio(codigo, correlativo, anio),
            codigo_sucursal=codigo,
            anio_folio=anio,
            correlativo=correlativo,
            marca=marca,
            cliente=cliente,
            representante=representante,
            cuenta_pago=cuenta,
            fecha_inicio=fecha_inicio,
            duracion_meses=duracion_meses,
            fecha_vencimiento=calcular_vencimiento(fecha_inicio, duracion_meses),
            renovacion_automatica=renovacion_automatica,
            dias_aviso_termino=dias_aviso_termino,
            email_aviso=email_aviso,
            movil_aviso=movil_aviso,
            ejecutivo_responsable=ejecutivo,
            estado=Contrato.Estado.BORRADOR if borrador else Contrato.Estado.VIGENTE,
        )
        contrato.full_clean(validate_unique=False, validate_constraints=False)
        contrato.save()
        for servicio in servicios:
            servicio.contrato = contrato
        ServicioContratado.objects.bulk_create(servicios)
    # TODO(RF-15): record the contract in the audit log (HU-30).
    return contrato


def _borrador_bloqueado(contrato: Contrato) -> Contrato:
    bloqueado = Contrato.objects.select_for_update().get(pk=contrato.pk)
    if bloqueado.estado != Contrato.Estado.BORRADOR:
        raise ContratoNoEditableError
    return bloqueado


def actualizar_borrador(  # noqa: PLR0913 - mirrors the portal form
    contrato: Contrato,
    *,
    lineas: Sequence[LineaContrato],
    fecha_inicio: date,
    duracion_meses: int,
    representante: RepresentanteLegal | None,
    email_aviso: str,
    movil_aviso: str,
) -> Contrato:
    """Change a draft before it is signed, keeping its folio.

    ASSUMPTION: pending validation with Easy Office. The branch heads the
    folio, so it cannot change: a client who wants another branch starts a
    new request.

    Raises:
        ContratoNoEditableError: The contract is no longer a draft.
        django.core.exceptions.ValidationError: Keyed by the offending field.
    """
    if not DuracionContrato.objects.filter(meses=duracion_meses, activa=True).exists():
        raise ValidationError({"duracion_meses": _("Not an offered duration.")})
    _validar_representante(contrato.cliente, representante, fecha_inicio)
    _validar_duracion_de_planes(lineas, duracion_meses)
    servicios = _servicios(lineas)
    if _codigo_sucursal(lineas, contrato.codigo_sucursal) != contrato.codigo_sucursal:
        raise ValidationError({"codigo_sucursal": _("The branch cannot change.")})

    with transaction.atomic():
        contrato = _borrador_bloqueado(contrato)
        contrato.fecha_inicio = fecha_inicio
        contrato.duracion_meses = duracion_meses
        contrato.fecha_vencimiento = calcular_vencimiento(fecha_inicio, duracion_meses)
        contrato.representante = representante
        contrato.email_aviso = email_aviso
        contrato.movil_aviso = movil_aviso
        contrato.full_clean(validate_unique=False, validate_constraints=False)
        contrato.save()
        contrato.servicios.all().delete()
        for servicio in servicios:
            servicio.contrato = contrato
        ServicioContratado.objects.bulk_create(servicios)
    # TODO(RF-15): record the change in the audit log (HU-30).
    return contrato


def activar_contrato(contrato: Contrato) -> Contrato:
    """Put a signed draft in force.

    Raises:
        ContratoNoEditableError: The contract is not a draft.
    """
    with transaction.atomic():
        contrato = _borrador_bloqueado(contrato)
        contrato.estado = Contrato.Estado.VIGENTE
        contrato.save(update_fields=["estado", "updated_at"])
    # TODO(RF-15): record the change in the audit log (HU-30).
    return contrato


def anular_borrador(contrato: Contrato) -> Contrato:
    """Annul a draft that will not be signed. Its folio is not reused.

    Raises:
        ContratoNoEditableError: The contract is not a draft.
    """
    with transaction.atomic():
        contrato = _borrador_bloqueado(contrato)
        contrato.estado = Contrato.Estado.ANULADO
        contrato.save(update_fields=["estado", "updated_at"])
    # TODO(RF-15): record the change in the audit log (HU-30).
    return contrato


def _validar_representante(
    cliente: Cliente,
    representante: RepresentanteLegal | None,
    fecha: date,
) -> None:
    """A company's signer must represent it on the start date.

    ASSUMPTION: pending validation with Easy Office. The signer may be added
    later, so a company contract can be created without one.
    """
    if representante is None:
        return
    if cliente.empresa_id is None:
        raise ValidationError(
            {"representante": _("A natural-person client signs for themselves.")},
        )
    if not representa_a(representante, cliente.empresa_id, fecha):
        raise ValidationError(
            {
                "representante": _(
                    "This person does not represent the client on that date.",
                ),
            },
        )


def _en_vigor(fecha: date) -> Q:
    """A started vigente contract that has not ended on ``fecha``."""
    return (Q(terminado_en__isnull=True) | Q(terminado_en__gte=fecha)) & (
        Q(renovacion_automatica=True) | Q(fecha_vencimiento__gte=fecha)
    )


def _iniciados(fecha: date) -> QuerySet[Contrato]:
    return Contrato.objects.filter(
        estado=Contrato.Estado.VIGENTE,
        fecha_inicio__lte=fecha,
    )


def contratos_vigentes(fecha: date) -> QuerySet[Contrato]:
    """Contracts in force on ``fecha``.

    A contract that renews automatically stays in force after its first
    expiry until it is terminated.
    """
    return _iniciados(fecha).filter(_en_vigor(fecha))


def resumen_vencimientos(fecha: date, dias_aviso: int) -> dict[str, int]:
    """Count contracts in force, about to expire and expired on ``fecha`` (RF-14).

    Drafts, terminated and annulled contracts never count, nor does a
    contract that has not started. ``activos`` are the contracts in force
    (``contratos_vigentes``); ``por_vencer`` those of them whose term ends
    within ``dias_aviso`` days, both ends inclusive; ``vencidos`` the
    contracts past their expiry that do not renew automatically and were
    neither terminated nor renewed, which an executive must act on. A
    contract counts as renewed when a non-annulled contract points at it
    (RN-10).

    ASSUMPTION: pending validation with Easy Office. The dashboard counts
    contracts (one folio, one expiry) rather than their service lines. An
    automatically renewing contract stays in force after its first term,
    as in ``contratos_vigentes``, and is never "por vencer" again: its
    rolling term end is not modelled until renewals are (RN-10, TA-17).
    """
    renovado = Exists(
        Contrato.objects.filter(contrato_anterior=OuterRef("pk")).exclude(
            estado=Contrato.Estado.ANULADO,
        ),
    )
    en_vigor = _en_vigor(fecha)
    sin_renovar = Q(renovado=False)
    en_aviso = Q(
        fecha_vencimiento__range=(fecha, fecha + timedelta(days=dias_aviso)),
    )
    vencido = Q(
        renovacion_automatica=False,
        fecha_vencimiento__lt=fecha,
        terminado_en__isnull=True,
    )
    return (
        _iniciados(fecha)
        .annotate(renovado=renovado)
        .aggregate(
            activos=Count("pk", filter=en_vigor),
            por_vencer=Count("pk", filter=en_vigor & sin_renovar & en_aviso),
            vencidos=Count("pk", filter=sin_renovar & vencido),
        )
    )


def ocupantes(inmueble: Oficina, fecha: date) -> list[Cliente]:
    """Clients domiciled at ``inmueble`` on ``fecha``, through their contracts.

    Replaces the former AsignacionDomicilio: a domicile is occupied by a
    contracted service located at the property.
    """
    contratos = (
        contratos_vigentes(fecha)
        .filter(servicios__inmueble=inmueble)
        .select_related("cliente__persona", "cliente__empresa")
        .order_by("cliente_id")
        .distinct()
    )
    por_id = {contrato.cliente_id: contrato.cliente for contrato in contratos}
    return list(por_id.values())


def opciones_contrato() -> dict[str, Any]:
    """What the contract form offers, gathered from each app's services."""
    return {
        "marcas": [
            {
                "id": marca.pk,
                "nombre": marca.nombre,
                "cuenta_pago_default": marca.cuenta_pago_default_id,
            }
            for marca in marcas_activas()
        ],
        "cuentas_pago": [
            {"id": cuenta.pk, "texto_contrato": cuenta.texto_contrato}
            for cuenta in cuentas_pago_activas()
        ],
        "duraciones": list(
            DuracionContrato.objects.filter(activa=True).values_list(
                "meses",
                flat=True,
            ),
        ),
        "ciclos_pago": [
            {"codigo": ciclo.codigo, "nombre": ciclo.nombre}
            for ciclo in ciclos_pago_activos()
        ],
        "sucursales": [
            {
                "id": oficina.pk,
                "codigo": oficina.codigo_sucursal,
                "nombre": oficina.nombre,
            }
            for oficina in sucursales_activas()
        ],
        "servicios": [
            {
                "codigo": servicio.codigo,
                "nombre": servicio.nombre,
                "precio_base": servicio.precio_base,
                "precio_incluye_iva": servicio.precio_incluye_iva,
                "ciclo_pago_default": (
                    servicio.ciclo_pago_default.codigo
                    if servicio.ciclo_pago_default
                    else None
                ),
            }
            for servicio in servicios_contratables()
        ],
    }


def contacto_de_aviso(cliente: Cliente) -> tuple[str, str]:
    """Email and mobile for notices: the client's latest contract's, if any.

    Falls back to the client's own email and phone.

    ASSUMPTION: pending validation with Easy Office. Whether the notice
    contact belongs to the company or its representative is open.
    """
    ultimo = (
        Contrato.objects.filter(cliente=cliente)
        .exclude(email_aviso="", movil_aviso="")
        .order_by("-created_at", "-pk")
        .first()
    )
    if ultimo is not None:
        return ultimo.email_aviso, ultimo.movil_aviso
    parte = cliente.parte
    return parte.email, parte.telefono
