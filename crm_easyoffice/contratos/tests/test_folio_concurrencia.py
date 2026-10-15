"""Concurrent contract creation never repeats a folio.

Each thread creates a contract on its own database connection, in a real
transaction, so the row lock in contratos.folio is what keeps the numbers
apart. Without it, two threads read the same counter and the unique
constraint on (anio_folio, correlativo) turns one insert into an
IntegrityError, which the test reports.

The threads only see committed rows. A transactional test case would commit,
but its teardown flushes the whole database, seeded catalogue included, and
with --reuse-db every later run would start without it. So the test keeps
the ordinary django_db marker (which also makes pytest-django set up the test
database) and commits only its own rows from a separate connection, in years
no other test uses, deleting exactly those afterwards.
"""

from __future__ import annotations

import threading
from datetime import date
from typing import TYPE_CHECKING
from typing import Any

import pytest
from django.db import connection

from crm_easyoffice.clientes.models import Cliente
from crm_easyoffice.clientes.models import Persona
from crm_easyoffice.clientes.tests.factories import ClienteFactory
from crm_easyoffice.contratos.models import Contrato
from crm_easyoffice.contratos.models import CorrelativoFolio
from crm_easyoffice.contratos.services import crear_contrato
from crm_easyoffice.contratos.tests.factories import INICIO
from crm_easyoffice.contratos.tests.factories import domicilio_en
from crm_easyoffice.contratos.tests.factories import marca

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = pytest.mark.django_db

HILOS = 8
ANIO_EXISTENTE = 2091
ANIO_NUEVO = 2092


def exigir_base_de_pruebas() -> None:
    """Never commit test rows outside the test database."""
    nombre = connection.settings_dict["NAME"]
    if not nombre.startswith("test_"):
        msg = f"Refusing to write committed rows to {nombre!r}."
        raise RuntimeError(msg)


def en_otra_conexion(funcion: Callable[[], Any]) -> Any:
    """Run ``funcion`` on a fresh connection, so what it writes is committed."""
    resultado: list[Any] = []
    errores: list[BaseException] = []

    def correr() -> None:
        try:
            exigir_base_de_pruebas()
            resultado.append(funcion())
        except BaseException as error:  # noqa: BLE001 - re-raised below
            errores.append(error)
        finally:
            connection.close()

    hilo = threading.Thread(target=correr)
    hilo.start()
    hilo.join()
    if errores:
        raise errores[0]
    return resultado[0] if resultado else None


def limpiar(clientes: list[Cliente]) -> None:
    ids = [cliente.pk for cliente in clientes]
    personas = [cliente.persona_id for cliente in clientes]
    Contrato.objects.filter(cliente_id__in=ids).delete()
    CorrelativoFolio.objects.filter(anio__in=[ANIO_EXISTENTE, ANIO_NUEVO]).delete()
    Cliente.objects.filter(pk__in=ids).delete()
    Persona.objects.filter(pk__in=personas).delete()


@pytest.fixture
def clientes_comprometidos():
    """HILOS committed clients, removed with their contracts afterwards."""
    clientes = en_otra_conexion(lambda: ClienteFactory.create_batch(HILOS))
    try:
        yield clientes
    finally:
        en_otra_conexion(lambda: limpiar(clientes))


def crear_a_la_vez(clientes, anio: int) -> tuple[list[str], list[BaseException]]:
    """Create one contract per client, all at once, each on its own connection."""
    lineas = [domicilio_en(codigo) for codigo in ("LF", "VL", "SA")]
    la_marca = marca()
    barrera = threading.Barrier(HILOS)
    folios: list[str] = []
    errores: list[BaseException] = []

    def crear(indice: int) -> None:
        try:
            barrera.wait()
            contrato = crear_contrato(
                cliente=clientes[indice],
                marca=la_marca,
                lineas=[lineas[indice % len(lineas)]],
                fecha_inicio=INICIO,
                duracion_meses=12,
                fecha_emision=date(anio, 6, 1),
            )
            folios.append(contrato.folio)
        except BaseException as error:  # noqa: BLE001 - reported by the test
            errores.append(error)
        finally:
            connection.close()

    hilos = [threading.Thread(target=crear, args=(i,)) for i in range(HILOS)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()
    return folios, errores


def correlativos(folios: list[str]) -> list[int]:
    return sorted(int(folio.split("-")[1]) for folio in folios)


def test_concurrent_creations_never_collide(clientes_comprometidos):
    en_otra_conexion(
        lambda: CorrelativoFolio.objects.create(anio=ANIO_EXISTENTE, ultimo=0),
    )

    folios, errores = crear_a_la_vez(clientes_comprometidos, ANIO_EXISTENTE)

    assert errores == []
    assert len(set(folios)) == HILOS
    assert correlativos(folios) == list(range(1, HILOS + 1))


def test_first_folio_of_a_new_year_under_concurrency(clientes_comprometidos):
    # No counter row yet: every thread races to create it.
    folios, errores = crear_a_la_vez(clientes_comprometidos, ANIO_NUEVO)

    assert errores == []
    assert correlativos(folios) == list(range(1, HILOS + 1))
    ultimo = en_otra_conexion(
        lambda: CorrelativoFolio.objects.get(anio=ANIO_NUEVO).ultimo,
    )
    assert ultimo == HILOS
