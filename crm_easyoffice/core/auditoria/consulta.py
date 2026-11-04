"""Reading the audit log (RF-17, UC-13): a record's history and readable names.

Models are reached through the app registry by their entity label, so
``core`` imports no other app.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.apps import apps
from django.db.models import Q

from crm_easyoffice.core.models import RegistroAuditoria

from .registro import ETIQUETAS
from .registro import HISTORIAL

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.db.models import Model
    from django.db.models import QuerySet

# A record's history follows HISTORIAL this deep at most.
PROFUNDIDAD = 4


def _modelo(entidad: str) -> type[Model] | None:
    try:
        return apps.get_model(entidad)
    except LookupError, ValueError:
        return None


def _filas(modelo: type[Model]) -> QuerySet:
    """Every row, ignoring any filtering default manager."""
    return modelo._base_manager.all()  # noqa: SLF001


def _hijas(entidad: str, columna: str, ids: set[int]) -> set[int]:
    """Rows of ``entidad`` pointing at ``ids``, including deleted ones.

    A deleted line is gone from its table but its creation and deletion in
    the log still carry the parent's id.
    """
    encontrados: set[int] = set()
    modelo = _modelo(entidad)
    if modelo is not None:
        encontrados.update(
            _filas(modelo)
            .filter(**{f"{columna}__in": ids})
            .values_list(
                "pk",
                flat=True,
            ),
        )
    en_log = RegistroAuditoria.objects.filter(entidad=entidad).filter(
        Q(**{f"valor_nuevo__{columna}__in": list(ids)})
        | Q(**{f"valor_anterior__{columna}__in": list(ids)}),
    )
    encontrados.update(i for i in en_log.values_list("registro_id", flat=True) if i)
    return encontrados


def _padres(entidad_hija: str, columna: str, ids: set[int]) -> set[int]:
    """The records that ``ids`` of ``entidad_hija`` point at through ``columna``."""
    modelo = _modelo(entidad_hija)
    if modelo is None:
        return set()
    valores = _filas(modelo).filter(pk__in=ids).values_list(columna, flat=True)
    return {v for v in valores if v}


def registros_relacionados(entidad: str, registro_id: int) -> dict[str, set[int]]:
    """The record and every record whose history belongs to it (HISTORIAL)."""
    registros: dict[str, set[int]] = {entidad: {registro_id}}
    pendientes = {entidad: {registro_id}}
    for _ in range(PROFUNDIDAD):
        siguientes: dict[str, set[int]] = {}
        for actual, ids in pendientes.items():
            for vinculo in HISTORIAL.get(actual, ()):
                if vinculo.hija:
                    nuevos = _hijas(vinculo.entidad, vinculo.columna, ids)
                else:
                    nuevos = _padres(actual, vinculo.columna, ids)
                nuevos -= registros.get(vinculo.entidad, set())
                if nuevos:
                    registros.setdefault(vinculo.entidad, set()).update(nuevos)
                    siguientes.setdefault(vinculo.entidad, set()).update(nuevos)
        if not siguientes:
            break
        pendientes = siguientes
    return registros


def historial(entidad: str, registro_id: int) -> QuerySet[RegistroAuditoria]:
    """The log entries of a record and its related records, newest first."""
    filtro = Q()
    for relacionada, ids in registros_relacionados(entidad, registro_id).items():
        filtro |= Q(entidad=relacionada, registro_id__in=ids)
    return RegistroAuditoria.objects.filter(filtro)


def nombre_entidad(entidad: str) -> str:
    modelo = _modelo(entidad)
    return str(modelo._meta.verbose_name) if modelo else entidad  # noqa: SLF001


def nombres_registros(
    entradas: Iterable[RegistroAuditoria],
) -> dict[tuple[str, int], str]:
    """A readable name for each record on a page: one query per entity."""
    por_entidad: dict[str, set[int]] = {}
    for entrada in entradas:
        if entrada.registro_id is not None and entrada.entidad in ETIQUETAS:
            por_entidad.setdefault(entrada.entidad, set()).add(entrada.registro_id)
    nombres: dict[tuple[str, int], str] = {}
    for entidad, ids in por_entidad.items():
        modelo = _modelo(entidad)
        if modelo is None:
            continue
        filas = (
            _filas(modelo)
            .filter(pk__in=ids)
            .values_list(
                "pk",
                ETIQUETAS[entidad],
            )
        )
        for pk, etiqueta in filas:
            if etiqueta:
                nombres[entidad, pk] = str(etiqueta)
    return nombres
