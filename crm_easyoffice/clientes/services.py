"""Queries and writes other apps may run against client records."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from crm_easyoffice.core.validators import normalize_rut

from .models import Cliente
from .models import CuentaCliente
from .models import Empresa
from .models import Persona
from .models import RepresentanteLegal
from .models import TipoCliente

if TYPE_CHECKING:
    from datetime import date


class RegistroRechazadoError(Exception):
    """The portal registration cannot go ahead with the data given.

    The cause is never exposed, so the response does not reveal which RUTs or
    emails are on record.
    """


def contar_clientes(desde: date, hasta: date) -> dict[str, int]:
    """Count clients for a period, with both bounds inclusive in local time.

    Args:
        desde: First day of the period.
        hasta: Last day of the period.

    Returns:
        ``total``, every client registered up to ``hasta``, and ``nuevos``,
        those registered within the period.
    """
    registrados = Cliente.objects.filter(created_at__date__lte=hasta)
    return {
        "total": registrados.count(),
        "nuevos": registrados.filter(created_at__date__gte=desde).count(),
    }


def guardar_parte(tipo: str, datos: dict[str, Any]) -> Persona | Empresa:
    """Create the Persona or Empresa for ``datos["rut"]``, or update it if on record."""
    modelo = Persona if tipo == TipoCliente.PERSONA else Empresa
    parte, _ = modelo.objects.update_or_create(rut=datos["rut"], defaults=datos)
    return parte


def registrar_cuenta_cliente(
    *,
    tipo: str,
    datos: dict[str, Any],
    password: str,
) -> CuentaCliente:
    """Open a portal account, creating the client when the RUT is new (HU-03).

    ASSUMPTION: pending validation with Easy Office. A RUT already on record is
    linked only when its email matches the one given and it has no account
    yet; otherwise the client must ask Easy Office. Email ownership is not
    verified.

    Args:
        tipo: ``persona`` or ``empresa``.
        datos: Fields of the Persona or Empresa, with a normalised ``rut`` and
            the ``email`` the account logs in with.
        password: Plain password, checked against the configured validators.

    Raises:
        RegistroRechazadoError: The email or RUT cannot take a new account.
        django.core.exceptions.ValidationError: The password is too weak.
    """
    User = get_user_model()  # noqa: N806
    email = datos["email"]
    validate_password(password, user=User(email=email))

    with transaction.atomic():
        if User.objects.filter(email__iexact=email).exists():
            raise RegistroRechazadoError

        modelo = Persona if tipo == TipoCliente.PERSONA else Empresa
        existente = modelo.objects.select_for_update().filter(rut=datos["rut"]).first()
        if existente is None:
            cliente = Cliente.objects.create(**{tipo: guardar_parte(tipo, datos)})
        else:
            if existente.email.casefold() != email.casefold():
                raise RegistroRechazadoError
            cliente = Cliente.objects.filter(**{tipo: existente}).first()
            if cliente is None:
                cliente = Cliente.objects.create(**{tipo: existente})
            elif cliente.cuentas.exists():
                raise RegistroRechazadoError

        user = User.objects.create_user(
            email=email,
            password=password,
            name=cliente.nombre,
        )
        # TODO(RF-15): record the registration in the audit log (HU-30).
        return CuentaCliente.objects.create(user=user, cliente=cliente)


def representa_a(
    representante: RepresentanteLegal,
    empresa_id: int,
    fecha: date,
) -> bool:
    """Whether ``representante`` may act for the company on ``fecha``.

    The representation must belong to that company, be active, and cover the
    date (vigente_hasta inclusive).
    """
    return (
        representante.empresa_id == empresa_id
        and representante.activo
        and representante.vigente_desde <= fecha
        and (
            representante.vigente_hasta is None or representante.vigente_hasta >= fecha
        )
    )


class RepresentanteNoDisponibleError(Exception):
    """The representative's RUT belongs to a person this client may not edit.

    The cause is never exposed, so a client cannot learn whether a RUT is on
    record.
    """


class ClienteNoEsEmpresaError(Exception):
    """The operation needs a company client."""


# What a client may type about their representative for a contract.
CAMPOS_REPRESENTANTE = [
    "rut",
    "nombres",
    "apellido_paterno",
    "apellido_materno",
    "domicilio",
    "comuna",
    "region",
]


def representacion_vigente(empresa: Empresa) -> RepresentanteLegal | None:
    """The company's most recent active representation, if any."""
    return (
        RepresentanteLegal.objects.filter(empresa=empresa, activo=True)
        .select_related("persona")
        .order_by("-vigente_desde", "-pk")
        .first()
    )


def datos_contratante(cliente: Cliente) -> dict[str, dict[str, Any]]:
    """What the client's own records hold for a contract form; blanks if none.

    Raises:
        ClienteNoEsEmpresaError: The client is a natural person.
    """
    if cliente.empresa_id is None:
        raise ClienteNoEsEmpresaError
    empresa = Empresa.objects.get(pk=cliente.empresa_id)
    representacion = representacion_vigente(empresa)
    persona = representacion.persona if representacion else None
    return {
        "empresa": {
            "rut": empresa.rut,
            "razon_social": empresa.razon_social,
            "giro": empresa.giro,
        },
        "representante": {
            campo: getattr(persona, campo, "") if persona else ""
            for campo in CAMPOS_REPRESENTANTE
        },
        "personeria": {
            "fecha_instrumento": (
                representacion.fecha_instrumento if representacion else None
            ),
            "sitio_o_notaria": representacion.sitio_o_notaria if representacion else "",
        },
    }


def guardar_datos_contratante(
    cliente: Cliente,
    *,
    empresa: dict[str, Any],
    representante: dict[str, Any],
    personeria: dict[str, Any],
) -> RepresentanteLegal:
    """Save what a client typed for a contract: company, signer, personería.

    The client edits only records that are theirs: their own company, and a
    person who already represents it. A new RUT creates the person.

    ASSUMPTION: pending validation with Easy Office. A new representation
    is valid from the date of its deed (fecha_instrumento).

    Args:
        cliente: A company client.
        empresa: ``rut`` (must be the client's), ``razon_social``, ``giro``.
        representante: ``CAMPOS_REPRESENTANTE``, with a normalised ``rut``.
        personeria: ``fecha_instrumento`` and ``sitio_o_notaria``.

    Raises:
        ClienteNoEsEmpresaError: The client is a natural person.
        RepresentanteNoDisponibleError: The RUT is someone else's record.
        django.core.exceptions.ValidationError: The company RUT is not the
            client's.
    """
    if cliente.empresa_id is None:
        raise ClienteNoEsEmpresaError
    if normalize_rut(empresa["rut"]) != cliente.empresa.rut:
        raise ValidationError(
            {"empresa": _("The company RUT must be the one on your account.")},
        )
    datos_persona = {campo: representante[campo] for campo in CAMPOS_REPRESENTANTE}
    datos_persona["rut"] = normalize_rut(datos_persona["rut"])

    with transaction.atomic():
        registro = Empresa.objects.select_for_update().get(pk=cliente.empresa_id)
        registro.razon_social = empresa["razon_social"]
        registro.giro = empresa["giro"]
        registro.save(update_fields=["razon_social", "giro", "updated_at"])

        persona = (
            Persona.objects.select_for_update().filter(rut=datos_persona["rut"]).first()
        )
        if persona is None:
            persona = Persona.objects.create(**datos_persona)
        elif persona.representaciones.filter(empresa=registro, activo=True).exists():
            for campo, valor in datos_persona.items():
                setattr(persona, campo, valor)
            persona.save()
        else:
            raise RepresentanteNoDisponibleError

        representacion = (
            persona.representaciones.filter(empresa=registro, activo=True)
            .order_by("-vigente_desde", "-pk")
            .first()
        )
        if representacion is None:
            representacion = RepresentanteLegal(
                persona=persona,
                empresa=registro,
                vigente_desde=personeria["fecha_instrumento"],
            )
        representacion.fecha_instrumento = personeria["fecha_instrumento"]
        representacion.sitio_o_notaria = personeria["sitio_o_notaria"]
        representacion.save()
    # TODO(RF-15): record the changes in the audit log (HU-30).
    return representacion
