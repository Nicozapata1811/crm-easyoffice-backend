"""Dashboard indicator and export tests. All client data here is synthetic."""

from __future__ import annotations

import importlib
from datetime import date
from datetime import datetime
from http import HTTPStatus
from io import BytesIO
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse
from openpyxl import load_workbook
from rest_framework.test import APIClient

from crm_easyoffice.clientes.models import Cliente
from crm_easyoffice.clientes.tests.factories import ClienteFactory
from crm_easyoffice.panel.services import calcular_indicadores
from crm_easyoffice.users.tests.factories import UserFactory

seed = importlib.import_module("crm_easyoffice.core.migrations.0002_seed_roles")

SANTIAGO = ZoneInfo("America/Santiago")
SEPTIEMBRE = {"desde": "2026-09-01", "hasta": "2026-09-30"}


def client_for(role: str) -> APIClient:
    user = UserFactory.create()
    user.groups.add(Group.objects.get(name=role))
    api_client = APIClient()
    api_client.force_authenticate(user)
    return api_client


def registrar_cliente(registrado: datetime) -> None:
    cliente = ClienteFactory.create()
    Cliente.objects.filter(pk=cliente.pk).update(created_at=registrado)


@pytest.fixture
def administrador(db) -> APIClient:
    return client_for(seed.ADMINISTRADOR)


@pytest.fixture
def clientes_de_ejemplo(db) -> None:
    registrar_cliente(datetime(2026, 8, 15, 12, tzinfo=SANTIAGO))
    registrar_cliente(datetime(2026, 9, 1, 0, 30, tzinfo=SANTIAGO))
    registrar_cliente(datetime(2026, 9, 30, 23, 30, tzinfo=SANTIAGO))
    registrar_cliente(datetime(2026, 10, 1, 9, tzinfo=SANTIAGO))


class TestIndicadores:
    def test_client_counts_are_real_and_inclusive_in_local_time(
        self,
        administrador,
        clientes_de_ejemplo,
    ):
        response = administrador.get(reverse("panel:indicadores"), SEPTIEMBRE)

        assert response.status_code == HTTPStatus.OK
        assert response.data["periodo"] == SEPTIEMBRE
        assert response.data["clientes"] == {"total": 3, "nuevos": 2}

    def test_payload_keeps_the_documented_shape(self, administrador):
        data = administrador.get(reverse("panel:indicadores"), SEPTIEMBRE).data

        assert set(data) == {
            "periodo",
            "clientes",
            "servicios",
            "ventas",
            "tramites_pendientes",
            "documentos_pendientes_firma",
            "datos_de_ejemplo",
        }
        assert "clientes" not in data["datos_de_ejemplo"]
        ventas = data["ventas"]
        assert sum(fila["monto"] for fila in ventas["por_servicio"]) == ventas["total"]
        assert sum(fila["monto"] for fila in ventas["por_ejecutivo"]) == ventas["total"]

    def test_example_figures_are_deterministic(self, db):
        desde, hasta = date(2026, 9, 1), date(2026, 9, 30)

        assert calcular_indicadores(desde, hasta) == calcular_indicadores(desde, hasta)

    @pytest.mark.parametrize(
        "params",
        [
            {},
            {"desde": "2026-09-01"},
            {"desde": "no-es-fecha", "hasta": "2026-09-30"},
            {"desde": "2026-09-30", "hasta": "2026-09-01"},
        ],
    )
    def test_rejects_an_invalid_period(self, administrador, params):
        response = administrador.get(reverse("panel:indicadores"), params)

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_requires_the_dashboard_permission(self, db):
        ejecutivo = client_for(seed.EJECUTIVO)

        for name in ("panel:indicadores", "panel:exportar"):
            response = ejecutivo.get(reverse(name), SEPTIEMBRE)
            assert response.status_code == HTTPStatus.FORBIDDEN


class TestExportar:
    def test_downloads_a_workbook_with_the_indicators(
        self,
        administrador,
        clientes_de_ejemplo,
    ):
        response = administrador.get(reverse("panel:exportar"), SEPTIEMBRE)

        assert response.status_code == HTTPStatus.OK
        assert response["Content-Type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml",
        )
        assert response["Content-Disposition"] == (
            'attachment; filename="panel-operativo_2026-09-01_2026-09-30.xlsx"'
        )

        libro = load_workbook(BytesIO(response.content))
        assert libro.sheetnames == [
            "Resumen",
            "Ventas por servicio",
            "Ventas por ejecutivo",
        ]
        filas = {
            fila[0]: fila[1:]
            for fila in libro["Resumen"].iter_rows(values_only=True)
            if fila[0]
        }
        assert filas["Total de clientes"][0] == 3  # noqa: PLR2004
        assert filas["Clientes nuevos"] == (2, "En el período")
        assert "Valor de ejemplo" in filas["Servicios activos"][1]

    def test_sales_sheets_add_up_to_the_total(self, administrador):
        indicadores = administrador.get(reverse("panel:indicadores"), SEPTIEMBRE).data
        response = administrador.get(reverse("panel:exportar"), SEPTIEMBRE)

        libro = load_workbook(BytesIO(response.content))
        for hoja in ("Ventas por servicio", "Ventas por ejecutivo"):
            total = next(
                fila
                for fila in libro[hoja].iter_rows(values_only=True)
                if fila[0] == "Total"
            )
            assert total[2] == indicadores["ventas"]["total"]
