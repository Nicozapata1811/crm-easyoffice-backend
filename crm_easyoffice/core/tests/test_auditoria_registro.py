"""The triggers in the database match ``core.auditoria.registro`` (RF-15, MD-16)."""

from __future__ import annotations

import pytest
from django.apps import apps
from django.db import connection

from crm_easyoffice.core.auditoria import registro
from crm_easyoffice.core.auditoria import sql

pytestmark = pytest.mark.django_db


def triggers_instalados() -> dict[str, tuple[str, tuple[str, ...]]]:
    """Each table's ``auditoria`` trigger: its function and its arguments."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.relname, p.proname, t.tgnargs, t.tgargs
            FROM pg_trigger t
            JOIN pg_class c ON c.oid = t.tgrelid
            JOIN pg_proc p ON p.oid = t.tgfoid
            WHERE t.tgname = %s AND NOT t.tgisinternal
            """,
            [sql.TRIGGER],
        )
        instalados = {}
        for tabla, funcion, cantidad, argumentos in cursor.fetchall():
            valores = bytes(argumentos).split(b"\x00")[:cantidad]
            instalados[tabla] = (funcion, tuple(v.decode() for v in valores))
    return instalados


def test_every_audited_table_has_its_trigger_as_declared():
    esperados = {
        auditada.tabla: (
            "core_auditoria_registrar",
            sql.argumentos_trigger(
                auditada.entidad,
                auditada.excluidos,
                registro.ENMASCARADOS,
            ),
        )
        for auditada in registro.AUDITADAS
    } | {
        relacion.tabla: (
            "core_auditoria_relacion",
            (relacion.entidad, relacion.columna, relacion.clave),
        )
        for relacion in registro.RELACIONES
    }

    assert triggers_instalados() == esperados


def test_every_table_is_either_audited_or_left_out_on_purpose():
    decididas = (
        {a.tabla for a in registro.AUDITADAS}
        | {r.tabla for r in registro.RELACIONES}
        | set(registro.NO_AUDITADAS)
    )
    tablas = {
        opciones.db_table
        for opciones in (m._meta for m in apps.get_models(include_auto_created=True))  # noqa: SLF001
        if opciones.managed and not opciones.proxy
    }

    assert tablas - decididas == set(), "Decide in core.auditoria.registro"
    assert decididas - tablas == set(), "Stale entries in core.auditoria.registro"


def test_the_log_itself_is_protected():
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT t.tgname FROM pg_trigger t
            JOIN pg_class c ON c.oid = t.tgrelid
            WHERE c.relname = %s AND NOT t.tgisinternal
            """,
            [sql.TABLA],
        )
        assert {fila[0] for fila in cursor.fetchall()} == {"inmutable", "sin_truncate"}
