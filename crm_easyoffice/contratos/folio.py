"""Contract folios: ``{branch}-{correlative}-{year}``, e.g. ``LF-0007-2026`` (RN-38).

The correlative is shared by every branch and brand and restarts each year,
like Easy Office's macro (the highest correlative of the year plus one).

Concurrency: the year's counter is a row in CorrelativoFolio, locked with
``SELECT ... FOR UPDATE`` inside the transaction that creates the contract.
A concurrent creation waits for that transaction to end, so no two contracts
get the same number, and a failed creation rolls its number back, so none is
skipped. A database sequence would do neither: sequences ignore rollbacks and
cannot restart per year without one sequence per year. The unique constraint
on (anio_folio, correlativo) backs this up.
"""

from __future__ import annotations

from django.conf import settings
from django.db import connection

from .models import CorrelativoFolio


def formatear_folio(
    codigo_sucursal: str,
    correlativo: int,
    anio: int,
    ancho: int | None = None,
) -> str:
    """Format a folio. A correlative wider than ``ancho`` is never truncated.

    Args:
        codigo_sucursal: Branch code, for example ``LF``.
        correlativo: Number within the year.
        anio: Year of issue.
        ancho: Zero-padding; ``CONTRATO_FOLIO_ANCHO`` when omitted.
    """
    ancho = settings.CONTRATO_FOLIO_ANCHO if ancho is None else ancho
    return f"{codigo_sucursal}-{correlativo:0{ancho}d}-{anio}"


def siguiente_correlativo(anio: int) -> int:
    """Take the next correlative of ``anio``. Call inside ``transaction.atomic``.

    The year's row stays locked until the caller's transaction ends.
    """
    if not connection.in_atomic_block:
        msg = "siguiente_correlativo must run inside the contract's transaction."
        raise RuntimeError(msg)

    # ON CONFLICT DO NOTHING: the first contract of a year creates the row; a
    # concurrent first contract waits for that insert and then reuses the row.
    CorrelativoFolio.objects.bulk_create(
        [CorrelativoFolio(anio=anio)],
        ignore_conflicts=True,
    )
    fila = CorrelativoFolio.objects.select_for_update().get(anio=anio)
    fila.ultimo += 1
    fila.save(update_fields=["ultimo"])
    return fila.ultimo
