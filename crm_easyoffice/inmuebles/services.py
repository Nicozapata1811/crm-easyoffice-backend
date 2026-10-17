"""Queries and writes other apps may run against properties."""

from __future__ import annotations

from pathlib import PurePath
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import Q

from crm_easyoffice.clientes.services import representa_a

from .models import Autorizante
from .models import Oficina
from .models import TipoInmueble
from .models import validar_documento_identidad

if TYPE_CHECKING:
    from datetime import date

    from django.core.files import File
    from django.db.models import QuerySet

# The placeholders 0003_seed_sucursales leaves until the admin fills them in.
CALLE_PENDIENTE = "Por completar"
ROL_PENDIENTE = "PENDIENTE-"

# A contract embeds the card as a picture: a PDF scan cannot be printed.
EXTENSIONES_IMAGEN = {".jpg", ".jpeg", ".png"}


def sucursales_activas() -> QuerySet[Oficina]:
    """Active branch offices, the ones whose code can head a folio."""
    return Oficina.objects.filter(
        tipo=TipoInmueble.OFICINA,
        activa=True,
        codigo_sucursal__isnull=False,
    ).order_by("codigo_sucursal")


def codigo_sucursal_de(inmueble_id: int) -> str | None:
    """The branch code of a property, or None for a warehouse."""
    return (
        Oficina.objects.filter(pk=inmueble_id)
        .values_list("codigo_sucursal", flat=True)
        .first()
    )


def autorizante_vigente(inmueble: Oficina, fecha: date) -> Autorizante | None:
    """Who authorises the use of ``inmueble`` on ``fecha``, if anyone.

    ASSUMPTION: pending validation with Easy Office. Should periods overlap,
    the most recent one wins; RN-43 does not say whether that can happen.
    """
    return (
        Autorizante.objects.filter(
            inmueble=inmueble,
            activo=True,
            vigente_desde__lte=fecha,
        )
        .filter(Q(vigente_hasta__isnull=True) | Q(vigente_hasta__gte=fecha))
        .select_related("persona", "empresa", "representante__persona")
        .order_by("-vigente_desde")
        .first()
    )


def _campo(reverso: bool) -> str:  # noqa: FBT001
    return "documento_identidad_reverso" if reverso else "documento_identidad"


def guardar_documento_identidad(
    autorizante: Autorizante,
    archivo: File,
    *,
    reverso: bool = False,
) -> None:
    """Store a side of the identity card, replacing any previous file.

    The file is validated like the model field. The old file is deleted only
    once the transaction commits, so a rollback never leaves the record
    pointing at a missing file.

    Raises:
        django.core.exceptions.ValidationError: The file is too large or is
            not a JPG, PNG or PDF.
    """
    validar_documento_identidad(archivo)
    campo = getattr(autorizante, _campo(reverso))
    anterior = campo.name

    campo.save(archivo.name, archivo, save=False)
    autorizante.save(update_fields=[_campo(reverso), "updated_at"])
    # TODO(RF-15): record the upload in the audit log (HU-30).
    if anterior:
        storage = campo.storage
        transaction.on_commit(lambda: storage.delete(anterior))


def abrir_documento_identidad(
    autorizante: Autorizante,
    *,
    reverso: bool = False,
) -> File:
    """Open a side of the identity card for reading.

    Callers must have checked ``inmuebles.descargar_documento_identidad``, or
    be generating a document that embeds it.

    Raises:
        FileNotFoundError: The authoriser has no such file on record.
    """
    campo = getattr(autorizante, _campo(reverso))
    if not campo:
        raise FileNotFoundError
    # TODO(RF-15): record each access in the audit log (HU-30).
    return campo.open("rb")


def _es_imagen(campo) -> bool:
    return bool(campo) and PurePath(campo.name).suffix.lower() in EXTENSIONES_IMAGEN


def problemas_para_domicilio(oficina: Oficina, fecha: date) -> list[str]:
    """What the domicile contract (PLT-01) needs from a branch and is missing.

    Empty when the branch can be offered for a contract starting on
    ``fecha``. The messages are for the executive who completes the data in
    the admin.
    """
    problemas = []
    if not oficina.activa:
        problemas.append("La sucursal está inactiva.")
    if not oficina.calle or oficina.calle == CALLE_PENDIENTE or not oficina.numero:
        problemas.append("Falta la dirección (calle y número).")
    if not oficina.comuna or not oficina.region:
        problemas.append("Falta la comuna o la región.")
    if not oficina.rol_avaluo or oficina.rol_avaluo.startswith(ROL_PENDIENTE):
        problemas.append("Falta el rol de avalúo.")
    if not oficina.unidad_sii:
        problemas.append("Falta la unidad del SII que nombra la autorización.")
    if not oficina.municipalidad:
        problemas.append("Falta la municipalidad que nombra la autorización.")
    return problemas + _problemas_autorizante(oficina, fecha)


def _problemas_autorizante(oficina: Oficina, fecha: date) -> list[str]:
    autorizante = autorizante_vigente(oficina, fecha)
    if autorizante is None:
        return [f"No hay un autorizante vigente al {fecha:%d-%m-%Y}."]
    if autorizante.empresa is None or autorizante.representante is None:
        return [
            "El autorizante debe ser una empresa con su representante legal (PLT-01).",
        ]

    problemas = []
    empresa = autorizante.empresa
    if not empresa.razon_social or not empresa.rut:
        problemas.append("Falta la razón social o el RUT de la empresa autorizante.")
    representante = autorizante.representante
    if not representa_a(representante, empresa.pk, fecha):
        problemas.append(
            "El representante no representa a la empresa autorizante en esa fecha.",
        )
    persona = representante.persona
    faltan = [
        nombre
        for nombre, valor in [
            ("RUT", persona.rut),
            ("nacionalidad", persona.nacionalidad),
            ("estado civil", persona.estado_civil),
            ("profesión", persona.profesion),
        ]
        if not valor
    ]
    if faltan:
        problemas.append(
            f"Faltan datos del representante del autorizante: {', '.join(faltan)}.",
        )
    if not _es_imagen(autorizante.documento_identidad):
        problemas.append("Falta el anverso de la cédula del autorizante (JPG o PNG).")
    if not _es_imagen(autorizante.documento_identidad_reverso):
        problemas.append("Falta el reverso de la cédula del autorizante (JPG o PNG).")
    return problemas


def sucursales_para_domicilio(fecha: date) -> list[Oficina]:
    """Active branches that can be offered for a domicile starting on ``fecha``."""
    return [
        oficina
        for oficina in sucursales_activas()
        if not problemas_para_domicilio(oficina, fecha)
    ]
