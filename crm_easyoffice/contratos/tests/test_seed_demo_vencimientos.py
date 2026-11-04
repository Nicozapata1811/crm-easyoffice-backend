"""Demo contracts for EVI-T14. All data is synthetic."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from crm_easyoffice.contratos.management.commands.seed_demo_vencimientos import (
    ADMINISTRADOR,
)
from crm_easyoffice.contratos.management.commands.seed_demo_vencimientos import (
    EJECUTIVO,
)
from crm_easyoffice.contratos.models import AlertaVencimiento
from crm_easyoffice.contratos.models import Contrato
from crm_easyoffice.contratos.services import detectar_vencimientos
from crm_easyoffice.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

COMANDO = "seed_demo_vencimientos"


@pytest.fixture
def usuarios():
    return {
        correo: UserFactory.create(email=correo)
        for correo in (EJECUTIVO, ADMINISTRADOR)
    }


@pytest.mark.usefixtures("usuarios")
def test_each_demo_contract_gets_the_alert_its_days_left_say(settings):
    settings.DEBUG = True

    call_command(COMANDO)

    hoy = timezone.localdate()
    assert detectar_vencimientos(hoy) == 4  # noqa: PLR2004
    assert sorted(
        (alerta.fecha_vencimiento - hoy).days
        for alerta in AlertaVencimiento.objects.all()
    ) == [5, 14, 29, 59]
    assert sorted(a.umbral_dias for a in AlertaVencimiento.objects.all()) == [
        7,
        15,
        30,
        60,
    ]


def test_it_covers_each_kind_of_responsible(settings, usuarios):
    settings.DEBUG = True

    call_command(COMANDO)

    hoy = timezone.localdate()
    responsables = {
        (contrato.fecha_vencimiento - hoy).days: contrato.ejecutivo_responsable
        for contrato in Contrato.objects.select_related("ejecutivo_responsable")
    }
    assert responsables == {
        5: usuarios[EJECUTIVO],
        14: usuarios[EJECUTIVO],
        29: usuarios[ADMINISTRADOR],
        59: None,
    }


@pytest.mark.usefixtures("usuarios")
def test_running_it_again_moves_the_same_contracts(settings):
    settings.DEBUG = True
    call_command(COMANDO)
    folios = set(Contrato.objects.values_list("folio", flat=True))
    Contrato.objects.update(
        fecha_inicio=timezone.localdate() - timedelta(days=500),
        fecha_vencimiento=timezone.localdate() - timedelta(days=100),
    )

    call_command(COMANDO)

    assert set(Contrato.objects.values_list("folio", flat=True)) == folios
    assert detectar_vencimientos(timezone.localdate()) == 4  # noqa: PLR2004


def test_it_needs_the_demo_users(settings):
    settings.DEBUG = True

    with pytest.raises(CommandError, match="seed_demo_usuarios"):
        call_command(COMANDO)


@pytest.mark.usefixtures("usuarios")
def test_it_refuses_with_debug_off_unless_forced(settings):
    settings.DEBUG = False

    with pytest.raises(CommandError, match="--force"):
        call_command(COMANDO)
    call_command(COMANDO, force=True)

    assert Contrato.objects.count() == 4  # noqa: PLR2004


@pytest.mark.usefixtures("usuarios")
def test_it_refuses_production_even_when_forced(settings):
    settings.SETTINGS_MODULE = "config.settings.production"

    with pytest.raises(CommandError, match="production"):
        call_command(COMANDO, force=True)

    assert not Contrato.objects.exists()
