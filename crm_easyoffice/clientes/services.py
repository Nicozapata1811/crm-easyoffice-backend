"""Queries and writes other apps may run against client records."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction

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
