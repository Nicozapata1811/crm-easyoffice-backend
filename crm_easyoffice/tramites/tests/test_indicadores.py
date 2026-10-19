"""Case figures for the dashboard (RF-14, RF-47). Every value here is synthetic."""

from __future__ import annotations

import importlib
from datetime import date
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import Group

from crm_easyoffice.clientes.tests.factories import CuentaClienteFactory
from crm_easyoffice.contratos.tests.factories import nuevo_contrato
from crm_easyoffice.tramites.models import MotivoPendiente
from crm_easyoffice.tramites.services import COMPLETADO
from crm_easyoffice.tramites.services import FIRMA
from crm_easyoffice.tramites.services import INICIADO
from crm_easyoffice.tramites.services import PAGO
from crm_easyoffice.tramites.services import PENDIENTE
from crm_easyoffice.tramites.services import en_firma
from crm_easyoffice.tramites.services import pendientes_por_motivo
from crm_easyoffice.tramites.services import ventas_por_ejecutivo
from crm_easyoffice.tramites.tests.factories import tramite_con_historia
from crm_easyoffice.users.tests.factories import UserFactory
from crm_easyoffice.ventas.models import Venta
from crm_easyoffice.ventas.tests.factories import ServicioFactory
from crm_easyoffice.ventas.tests.factories import venta_pagada

pytestmark = pytest.mark.django_db

seed = importlib.import_module("crm_easyoffice.core.migrations.0002_seed_roles")

SANTIAGO = ZoneInfo("America/Santiago")
PAGADA = datetime(2026, 9, 10, 12, tzinfo=SANTIAGO)


def en_santiago(*partes: int) -> datetime:
    return datetime(*partes, tzinfo=SANTIAGO)


def ejecutivo(nombre: str, **campos):
    user = UserFactory.create(name=nombre, **campos)
    user.groups.add(Group.objects.get(name=seed.EJECUTIVO))
    return user


def venta_de(monto: int) -> Venta:
    servicio = ServicioFactory.create(precio_base=Decimal(monto))
    return venta_pagada(PAGADA, (servicio, 1))


class TestVentasPorEjecutivo:
    def test_attributes_each_sale_through_its_case(self):
        responsable = ejecutivo("Ejecutiva Uno de Prueba")
        quien_abrio = ejecutivo("Ejecutivo Dos de Prueba")
        cliente_portal = CuentaClienteFactory.create().user

        del_contrato = venta_de(40000)
        tramite_con_historia(
            (PAGADA, COMPLETADO, None),
            venta=del_contrato,
            contrato=nuevo_contrato(ejecutivo=responsable),
        )
        abierta_por_staff = venta_de(30000)
        tramite_con_historia(
            (PAGADA, COMPLETADO, None),
            venta=abierta_por_staff,
            contrato=nuevo_contrato(),
            creado_por=quien_abrio,
        )
        abierta_en_portal = venta_de(20000)
        tramite_con_historia(
            (PAGADA, COMPLETADO, None),
            venta=abierta_en_portal,
            contrato=nuevo_contrato(),
            creado_por=cliente_portal,
        )
        venta_de(10000)  # bought in the portal, with no case

        filas = ventas_por_ejecutivo(Venta.objects.all())

        assert filas == [
            {"ejecutivo": "Ejecutiva Uno de Prueba", "monto": 40000, "cantidad": 1},
            {"ejecutivo": "Ejecutivo Dos de Prueba", "monto": 30000, "cantidad": 1},
            {"ejecutivo": None, "monto": 30000, "cantidad": 2},
        ]

    def test_contract_executive_wins_over_who_opened_the_case(self):
        responsable = ejecutivo("Ejecutiva Uno de Prueba")
        venta = venta_de(40000)
        tramite_con_historia(
            (PAGADA, COMPLETADO, None),
            venta=venta,
            contrato=nuevo_contrato(ejecutivo=responsable),
            creado_por=ejecutivo("Ejecutivo Dos de Prueba"),
        )

        assert ventas_por_ejecutivo(Venta.objects.all()) == [
            {"ejecutivo": "Ejecutiva Uno de Prueba", "monto": 40000, "cantidad": 1},
        ]

    def test_an_executive_without_a_name_shows_the_email(self):
        responsable = ejecutivo("", email="ejecutivo@prueba.example")
        venta = venta_de(40000)
        tramite_con_historia(
            (PAGADA, COMPLETADO, None),
            venta=venta,
            contrato=nuevo_contrato(ejecutivo=responsable),
        )

        assert ventas_por_ejecutivo(Venta.objects.all())[0]["ejecutivo"] == (
            "ejecutivo@prueba.example"
        )

    def test_no_sales_give_no_rows(self):
        assert ventas_por_ejecutivo(Venta.objects.none()) == []


@pytest.fixture
def historias() -> None:
    # Pending payment through September, completed in October.
    tramite_con_historia(
        (en_santiago(2026, 9, 1, 10), INICIADO, None),
        (en_santiago(2026, 9, 10, 10), PENDIENTE, PAGO),
        (en_santiago(2026, 10, 5, 10), COMPLETADO, None),
    )
    # Waiting for a signature from the last evening of September.
    tramite_con_historia(
        (en_santiago(2026, 9, 20, 10), INICIADO, None),
        (en_santiago(2026, 9, 30, 23, 30), PENDIENTE, FIRMA),
    )
    # Opened in October.
    tramite_con_historia(
        (en_santiago(2026, 10, 2, 10), INICIADO, None),
        (en_santiago(2026, 10, 3, 10), PENDIENTE, FIRMA),
    )


def nombre(codigo: str) -> str:
    return MotivoPendiente.objects.get(codigo=codigo).nombre


class TestPendientesPorMotivo:
    def test_reads_each_case_state_at_the_end_of_the_day(self, historias):
        assert pendientes_por_motivo(date(2026, 9, 30)) == [
            {"motivo": FIRMA, "nombre": nombre(FIRMA), "cantidad": 1},
            {"motivo": PAGO, "nombre": nombre(PAGO), "cantidad": 1},
        ]

    def test_a_later_day_sees_the_later_moves(self, historias):
        assert pendientes_por_motivo(date(2026, 10, 10)) == [
            {"motivo": FIRMA, "nombre": nombre(FIRMA), "cantidad": 2},
        ]

    def test_before_any_case_nothing_is_pending(self, historias):
        assert pendientes_por_motivo(date(2026, 8, 31)) == []

    def test_cases_waiting_for_a_signature(self, historias):
        assert en_firma(date(2026, 9, 29)).count() == 0
        assert en_firma(date(2026, 9, 30)).count() == 1
        assert en_firma(date(2026, 10, 10)).count() == 2  # noqa: PLR2004
