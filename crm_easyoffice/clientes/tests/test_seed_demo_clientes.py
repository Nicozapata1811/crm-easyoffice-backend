from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from crm_easyoffice.clientes.models import Cliente
from crm_easyoffice.core.validators import validate_rut

pytestmark = pytest.mark.django_db


def test_creates_valid_fictitious_clients(settings):
    settings.DEBUG = True

    call_command("seed_demo_clientes", cantidad=12)

    clientes = Cliente.objects.select_related("persona", "empresa")
    assert clientes.count() == 12  # noqa: PLR2004
    assert clientes.filter(empresa__isnull=False).exists()
    for cliente in clientes:
        validate_rut(cliente.parte.rut)
        assert cliente.parte.email.endswith("example.test")
        assert cliente.folio


def test_running_twice_creates_nothing_new(settings):
    settings.DEBUG = True

    call_command("seed_demo_clientes", cantidad=6)
    call_command("seed_demo_clientes", cantidad=6)

    assert Cliente.objects.count() == 6  # noqa: PLR2004


def test_refuses_without_debug(settings):
    settings.DEBUG = False

    with pytest.raises(CommandError):
        call_command("seed_demo_clientes")

    assert not Cliente.objects.exists()
