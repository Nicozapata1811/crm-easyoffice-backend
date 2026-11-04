"""Queries and writes other apps may run against properties."""

from __future__ import annotations

from pathlib import PurePath
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import Prefetch
from django.db.models import Q

from crm_easyoffice.clientes.services import representa_a
from crm_easyoffice.core.auditoria.eventos import Accion
from crm_easyoffice.core.auditoria.eventos import registrar_evento

from .models import Autorizante
from .models import Oficina
from .models import TipoInmueble
from .models import validar_documento_identidad

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date

    from django.core.files import File
    from django.db.models import QuerySet

    from crm_easyoffice.clientes.models import Persona

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

    A property listed by ``inmuebles_para`` carries its active authorisations
    already; they are filtered here without another query.
    """
    cargadas = getattr(inmueble, "autorizaciones_activas", None)
    if cargadas is not None:
        return next(
            (
                a
                for a in cargadas
                if a.vigente_desde <= fecha
                and (a.vigente_hasta is None or a.vigente_hasta >= fecha)
            ),
            None,
        )
    return (
        _autorizaciones_activas()
        .filter(inmueble=inmueble, vigente_desde__lte=fecha)
        .filter(Q(vigente_hasta__isnull=True) | Q(vigente_hasta__gte=fecha))
        .first()
    )


def _autorizaciones_activas() -> QuerySet[Autorizante]:
    return (
        Autorizante.objects.filter(activo=True)
        .select_related("persona", "empresa", "representante__persona")
        .order_by("-vigente_desde")
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
    archivo = campo.open("rb")
    registrar_evento(
        Accion.ACCESO_DOCUMENTO_IDENTIDAD,
        entidad="inmuebles.autorizante",
        registro_id=autorizante.pk,
        datos={"lado": "reverso" if reverso else "anverso"},
    )
    return archivo


def _es_imagen(campo) -> bool:
    return bool(campo) and PurePath(campo.name).suffix.lower() in EXTENSIONES_IMAGEN


def problemas_de_ubicacion(inmueble: Oficina) -> list[str]:
    """What a contract needs to print where a property is: street, comuna, region."""
    problemas = []
    if not inmueble.calle or inmueble.calle == CALLE_PENDIENTE or not inmueble.numero:
        problemas.append("Falta la dirección (calle y número).")
    if not inmueble.comuna or not inmueble.region:
        problemas.append("Falta la comuna o la región.")
    return problemas


def _problemas_rol(inmueble: Oficina) -> list[str]:
    if not inmueble.rol_avaluo or inmueble.rol_avaluo.startswith(ROL_PENDIENTE):
        return ["Falta el rol de avalúo."]
    return []


def problemas_para_ubicar(oficina: Oficina, fecha: date) -> list[str]:
    """What a contract that only names a branch (PLT-02) needs from it.

    PLT-02 prints the branch's address, comuna and region, nothing else.
    """
    inactiva = [] if oficina.activa else ["La sucursal está inactiva."]
    return inactiva + problemas_de_ubicacion(oficina)


def problemas_para_domicilio(oficina: Oficina, fecha: date) -> list[str]:
    """What the domicile contract (PLT-01) needs from a branch and is missing.

    Empty when the branch can be offered for a contract starting on
    ``fecha``. The messages are for the executive who completes the data in
    the admin.
    """
    problemas = [
        *problemas_para_ubicar(oficina, fecha),
        *_problemas_rol(oficina),
    ]
    if not oficina.unidad_sii:
        problemas.append("Falta la unidad del SII que nombra la autorización.")
    if not oficina.municipalidad:
        problemas.append("Falta la municipalidad que nombra la autorización.")
    return problemas + _problemas_autorizante_empresa(oficina, fecha)


def problemas_para_bodega(bodega: Oficina, fecha: date) -> list[str]:
    """What the warehouse contract (PLT-02) needs from a warehouse and is missing.

    Its address, comuna, region and rol, and a current owner who is a natural
    person with every field the authorisation prints and both card sides.
    """
    problemas = [] if bodega.activa else ["La bodega está inactiva."]
    if bodega.tipo != TipoInmueble.BODEGA:
        problemas.append("El inmueble no es una bodega.")
    problemas += [*problemas_de_ubicacion(bodega), *_problemas_rol(bodega)]
    return problemas + _problemas_autorizante_persona(bodega, fecha)


def _sin_autorizante(fecha: date) -> list[str]:
    return [f"No hay un autorizante vigente al {fecha:%d-%m-%Y}."]


def _faltan_datos_civiles(persona: Persona, quien: str) -> list[str]:
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
        return [f"Faltan datos {quien}: {', '.join(faltan)}."]
    return []


def _problemas_cedula(autorizante: Autorizante) -> list[str]:
    problemas = []
    if not _es_imagen(autorizante.documento_identidad):
        problemas.append("Falta el anverso de la cédula del autorizante (JPG o PNG).")
    if not _es_imagen(autorizante.documento_identidad_reverso):
        problemas.append("Falta el reverso de la cédula del autorizante (JPG o PNG).")
    return problemas


def _problemas_autorizante_empresa(oficina: Oficina, fecha: date) -> list[str]:
    autorizante = autorizante_vigente(oficina, fecha)
    if autorizante is None:
        return _sin_autorizante(fecha)
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
    problemas += _faltan_datos_civiles(
        representante.persona,
        "del representante del autorizante",
    )
    return problemas + _problemas_cedula(autorizante)


def _problemas_autorizante_persona(bodega: Oficina, fecha: date) -> list[str]:
    autorizante = autorizante_vigente(bodega, fecha)
    if autorizante is None:
        return _sin_autorizante(fecha)
    if autorizante.persona is None:
        return ["El autorizante de una bodega debe ser una persona natural (PLT-02)."]
    return [
        *_faltan_datos_civiles(autorizante.persona, "del autorizante"),
        *_problemas_cedula(autorizante),
    ]


# What each case type's configuration may ask of a property (``requisitos``):
# the profile is what its template prints about that property.
REQUISITOS: dict[str, Callable[[Oficina, date], list[str]]] = {
    "domicilio": problemas_para_domicilio,
    "ubicacion": problemas_para_ubicar,
    "bodega": problemas_para_bodega,
}


def bodegas_activas() -> QuerySet[Oficina]:
    """Active warehouses, which carry no branch code."""
    return Oficina.objects.filter(tipo=TipoInmueble.BODEGA, activa=True).order_by(
        "region",
        "comuna",
        "nombre",
    )


# The property a case type's line names (``inmueble``) and where it is chosen.
ROLES: dict[str, Callable[[], QuerySet[Oficina]]] = {
    "sucursal": sucursales_activas,
    "bodega": bodegas_activas,
}


def problemas_inmueble(inmueble: Oficina, fecha: date, requisito: str) -> list[str]:
    """What profile ``requisito`` needs from ``inmueble`` on ``fecha``.

    Raises:
        KeyError: The profile is unknown (a configuration error).
    """
    return REQUISITOS[requisito](inmueble, fecha)


def inmuebles_para(rol: str, fecha: date, requisito: str) -> list[Oficina]:
    """The properties of ``rol`` that meet ``requisito`` for a start on ``fecha``.

    Their active authorisations are loaded in one query, so checking each
    property's owner costs nothing more.

    Raises:
        KeyError: The role or the profile is unknown (a configuration error).
    """
    chequeo = REQUISITOS[requisito]
    inmuebles = ROLES[rol]().prefetch_related(
        Prefetch(
            "autorizaciones",
            queryset=_autorizaciones_activas(),
            to_attr="autorizaciones_activas",
        ),
    )
    return [inmueble for inmueble in inmuebles if not chequeo(inmueble, fecha)]


def inmueble_de(rol: str, pk: int) -> Oficina | None:
    """The active property ``pk`` if it can play ``rol``.

    Raises:
        KeyError: The role is unknown (a configuration error).
    """
    return ROLES[rol]().filter(pk=pk).first()


def sucursales_para_domicilio(fecha: date) -> list[Oficina]:
    """Active branches that can be offered for a domicile starting on ``fecha``."""
    return inmuebles_para("sucursal", fecha, "domicilio")
