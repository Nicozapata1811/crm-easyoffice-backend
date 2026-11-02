from __future__ import annotations

import pytest
from django.contrib.auth import authenticate
from django.core.management import call_command
from django.core.management.base import CommandError

from crm_easyoffice.clientes.models import CuentaCliente
from crm_easyoffice.users.management.commands.seed_demo_usuarios import CLIENTES
from crm_easyoffice.users.models import User

pytestmark = pytest.mark.django_db

CLAVES = {
    "STAGING_DEMO_ADMIN_PASSWORD": "clave-Admin-demo-81",
    "STAGING_DEMO_EJECUTIVO_PASSWORD": "clave-Ejecutivo-demo-82",
    "STAGING_DEMO_CLIENTE1_PASSWORD": "clave-Cliente-demo-83",
    "STAGING_DEMO_CLIENTE2_PASSWORD": "clave-Cliente-demo-84",
}


@pytest.fixture
def claves(monkeypatch) -> None:
    for variable, valor in CLAVES.items():
        monkeypatch.setenv(variable, valor)


@pytest.mark.usefixtures("claves")
def test_it_creates_the_staff_and_the_portal_clients():
    call_command("seed_demo_usuarios", force=True)

    admin = User.objects.get(email="admin@example.test")
    assert admin.is_staff
    assert admin.has_perm("clientes.view_cliente")
    assert list(admin.groups.values_list("name", flat=True)) == ["Administrador"]
    ejecutivo = User.objects.get(email="ejecutivo@example.test")
    assert list(ejecutivo.groups.values_list("name", flat=True)) == ["Ejecutivo"]
    cuentas = CuentaCliente.objects.select_related("cliente__empresa")
    assert cuentas.count() == len(CLIENTES)
    assert all(cuenta.cliente.es_empresa for cuenta in cuentas)


@pytest.mark.usefixtures("claves")
def test_running_it_again_resets_the_passwords(monkeypatch):
    call_command("seed_demo_usuarios", force=True)
    monkeypatch.setenv("STAGING_DEMO_CLIENTE1_PASSWORD", "otra-Clave-demo-85")

    call_command("seed_demo_usuarios", force=True)

    assert CuentaCliente.objects.count() == len(CLIENTES)
    assert authenticate(
        username="cliente1@example.test",
        password="otra-Clave-demo-85",  # noqa: S106 - a test value
    )


def test_it_refuses_with_debug_off_without_force(settings):
    settings.DEBUG = False
    with pytest.raises(CommandError, match="--force"):
        call_command("seed_demo_usuarios")


def test_it_refuses_a_password_left_as_changeme(monkeypatch, claves):
    monkeypatch.setenv("STAGING_DEMO_ADMIN_PASSWORD", "CHANGEME")
    with pytest.raises(CommandError, match="STAGING_DEMO_ADMIN_PASSWORD"):
        call_command("seed_demo_usuarios", force=True)
