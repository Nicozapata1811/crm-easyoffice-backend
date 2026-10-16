from __future__ import annotations

from datetime import date

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from crm_easyoffice.configuracion.services import problemas_para_contrato
from crm_easyoffice.inmuebles.models import Autorizante
from crm_easyoffice.inmuebles.models import Oficina
from crm_easyoffice.inmuebles.services import sucursales_para_domicilio

pytestmark = pytest.mark.django_db

HOY = date(2026, 10, 16)


def test_makes_every_branch_ready_for_plt01(settings):
    settings.DEBUG = True

    call_command("seed_demo_domicilio")

    assert [o.codigo_sucursal for o in sucursales_para_domicilio(HOY)] == [
        "LF",
        "SA",
        "VL",
    ]
    assert problemas_para_contrato("EASY OFFICE") == []


def test_never_overwrites_admin_data(settings):
    settings.DEBUG = True
    Oficina.objects.filter(codigo_sucursal="LF").update(calle="Calle Real Completada")

    call_command("seed_demo_domicilio")
    call_command("seed_demo_domicilio")

    assert Oficina.objects.get(codigo_sucursal="LF").calle == "Calle Real Completada"
    assert Autorizante.objects.count() == 2  # noqa: PLR2004


def test_refuses_without_debug(settings):
    settings.DEBUG = False

    with pytest.raises(CommandError):
        call_command("seed_demo_domicilio")

    assert not Autorizante.objects.exists()
