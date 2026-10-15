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
    from crm_easyoffice.ventas.models import Servicio


@dataclass(frozen=True)
class LineaContrato:
    """A service to contract, as the executive chose it.

    ``ciclo_pago`` defaults to the service's cycle. ``precio`` is given only
    for a service without a fixed price; otherwise the list price is copied.
    """

    servicio: Servicio
    ciclo_pago: CicloPago | None = None
    inmueble: Oficina | None = None
    precio: Decimal | None = None


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
                precio=_precio(servicio, linea.precio),
                precio_incluye_iva=servicio.precio_incluye_iva,
                ciclo_pago=ciclo,
                inmueble=linea.inmueble,
            ),
        )
    return copiados


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
) -> Contrato:
    """Record a contract with its services and give it the next folio.

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
        )
        contrato.full_clean(validate_unique=False, validate_constraints=False)
        contrato.save()
        for servicio in servicios:
            servicio.contrato = contrato
        ServicioContratado.objects.bulk_create(servicios)
    # TODO(RF-15): record the contract in the audit log (HU-30).
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


def contratos_vigentes(fecha: date) -> QuerySet[Contrato]:
    """Contracts in force on ``fecha``.

    A contract that renews automatically stays in force after its first
    expiry until it is terminated.
    """
    return (
        Contrato.objects.filter(estado=Contrato.Estado.VIGENTE, fecha_inicio__lte=fecha)
        .filter(Q(terminado_en__isnull=True) | Q(terminado_en__gte=fecha))
        .filter(Q(renovacion_automatica=True) | Q(fecha_vencimiento__gte=fecha))
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
