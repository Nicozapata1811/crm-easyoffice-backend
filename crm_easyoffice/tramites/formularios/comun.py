"""What the per-template forms share: party blocks, fields and formats."""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING
from typing import Any

from django.utils import timezone
from rest_framework import serializers

from crm_easyoffice.clientes.api.serializers import RutField
from crm_easyoffice.clientes.services import CAMPOS_PERSONA
from crm_easyoffice.clientes.services import PersonaConOtrosDatosError
from crm_easyoffice.clientes.services import guardar_persona_de_tramite
from crm_easyoffice.tramites.models import Tramite

if TYPE_CHECKING:
    from crm_easyoffice.clientes.models import Cliente
    from crm_easyoffice.clientes.models import Persona

MAX_MONTO = 999_999_999
# A term prints in words, which documentos.formato writes up to 99.
MAX_MESES = 99

FECHA_FUTURA = "La fecha del documento no puede ser futura."
OTROS_DATOS = (
    "Esta persona ya está registrada con otro dato. Escribe el registrado o "
    "corrígelo en su ficha."
)

# ASSUMPTION: pending validation with Easy Office. Chilean plates: cars
# AA1111 (until 2007) and BBBB11; motorcycles AA111 and BBB11. Stored in
# capitals without separators.
PATENTE = re.compile(r"^([A-Z]{2}\d{4}|[A-Z]{4}\d{2}|[A-Z]{3}\d{2}|[A-Z]{2}\d{3})$")
PATENTE_INVALIDA = "Escribe una patente chilena, por ejemplo BBDF12 o AB1234."


class DatosDePersonaError(Exception):
    """A party block names a person on record with other data.

    ``bloque`` is the form's key for that party and ``campos`` the fields
    that differ; the API answers a 400 on those fields.
    """

    def __init__(self, bloque: str, campos: list[str]) -> None:
        super().__init__(f"{bloque}: {', '.join(campos)}")
        self.bloque = bloque
        self.campos = campos


class PatenteField(serializers.CharField):
    def to_internal_value(self, data: Any) -> str:
        valor = re.sub(r"[\s.\-·]", "", super().to_internal_value(data)).upper()
        if not PATENTE.match(valor):
            raise serializers.ValidationError(PATENTE_INVALIDA)
        return valor


class PersonaSerializer(serializers.Serializer):
    """A party who is a natural person: name, RUT, domicile and email.

    The email is where an advanced signature sends the signer's link.
    """

    rut = RutField()
    nombres = serializers.CharField(max_length=100)
    apellido_paterno = serializers.CharField(max_length=100)
    apellido_materno = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        default="",
    )
    domicilio = serializers.CharField(max_length=255)
    comuna = serializers.CharField(max_length=100)
    email = serializers.EmailField(required=False, allow_blank=True, default="")


def fecha_documento(valor: date) -> date:
    """A document is dated today or earlier, never ahead."""
    if valor > timezone.localdate():
        raise serializers.ValidationError(FECHA_FUTURA)
    return valor


def personas_propias(cliente: Cliente) -> set[int]:
    """Persons recorded as parties of this client's cases (``datos.personas``)."""
    propias: set[int] = set()
    for ids in Tramite.objects.filter(cliente=cliente).values_list(
        "datos__personas",
        flat=True,
    ):
        propias.update(ids or [])
    return propias


def guardar_parte(cliente: Cliente, bloque: str, datos: dict[str, Any]) -> Persona:
    """Find or create the person of a party block (clientes' rule).

    Raises:
        DatosDePersonaError: The person is on record with other data and is
            not this client's to edit.
    """
    try:
        return guardar_persona_de_tramite(
            cliente,
            datos,
            propias=personas_propias(cliente),
        )
    except PersonaConOtrosDatosError as error:
        raise DatosDePersonaError(bloque, error.campos) from None


def ficha(persona: Persona | None) -> dict[str, str]:
    """A person as a party block's payload; blanks when there is none."""
    return {
        "rut": persona.rut if persona else "",
        **{
            campo: getattr(persona, campo, "") if persona else ""
            for campo in CAMPOS_PERSONA
        },
    }


def linea(etiqueta: str, valor: Any) -> dict[str, str]:
    return {"etiqueta": etiqueta, "valor": str(valor)}


def fecha_corta(valor: str | date) -> str:
    """``2026-11-09`` → ``09-11-2026``."""
    if isinstance(valor, str):
        valor = date.fromisoformat(valor)
    return f"{valor:%d-%m-%Y}"


def pesos(valor: int) -> str:
    """``30000`` → ``$30.000``."""
    return "$" + f"{int(valor):,}".replace(",", ".")
