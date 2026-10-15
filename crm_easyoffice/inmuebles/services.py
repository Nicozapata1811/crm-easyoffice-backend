"""Queries and writes other apps may run against properties."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import Q

from .models import Autorizante
from .models import Oficina
from .models import TipoInmueble
from .models import validar_documento_identidad

if TYPE_CHECKING:
    from datetime import date

    from django.core.files import File
    from django.db.models import QuerySet


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


def guardar_documento_identidad(autorizante: Autorizante, archivo: File) -> None:
    """Store a new identity card for ``autorizante``, replacing any previous one.

    The file is validated like the model field. The old file is deleted only
    once the transaction commits, so a rollback never leaves the record
    pointing at a missing file.

    Raises:
        django.core.exceptions.ValidationError: The file is too large or is
            not a JPG, PNG or PDF.
    """
    validar_documento_identidad(archivo)
    anterior = autorizante.documento_identidad.name

    autorizante.documento_identidad.save(archivo.name, archivo, save=False)
    autorizante.save(update_fields=["documento_identidad", "updated_at"])
    # TODO(RF-15): record the upload in the audit log (HU-30).
    if anterior:
        storage = autorizante.documento_identidad.storage
        transaction.on_commit(lambda: storage.delete(anterior))


def abrir_documento_identidad(autorizante: Autorizante) -> File:
    """Open the identity card for reading.

    Callers must have checked ``inmuebles.descargar_documento_identidad``.

    Raises:
        FileNotFoundError: The authoriser has no identity card on record.
    """
    if not autorizante.documento_identidad:
        raise FileNotFoundError
    # TODO(RF-15): record each access in the audit log (HU-30).
    return autorizante.documento_identidad.open("rb")
