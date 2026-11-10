"""The demo cases of the documents implemented directly. Synthetic data only.

Here, not under tramites, because generating them needs the seeded templates
in storage (this folder's conftest).
"""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from crm_easyoffice.clientes.models import TipoCliente
from crm_easyoffice.clientes.services import registrar_cuenta_cliente
from crm_easyoffice.core.validators import validate_rut
from crm_easyoffice.tramites.management.commands import seed_demo_documentos as seed
from crm_easyoffice.tramites.models import Tramite

pytestmark = pytest.mark.django_db


@pytest.fixture
def cliente_demo():
    return registrar_cuenta_cliente(
        tipo=TipoCliente.EMPRESA,
        datos={
            "rut": seed.RUT_CLIENTE,
            "razon_social": "Empresa Demo Uno SpA",
            "giro": "Servicios de demostración",
            "email": "cliente1@example.test",
        },
        password="synthetic-Pass-123",  # noqa: S106
    ).cliente


def test_it_refuses_without_debug_or_the_demo_client(settings):
    settings.DEBUG = False
    with pytest.raises(CommandError, match="DEBUG"):
        call_command("seed_demo_documentos")
    with pytest.raises(CommandError, match="seed_demo_usuarios"):
        call_command("seed_demo_documentos", force=True)


def test_it_starts_one_case_per_document_once(
    cliente_demo,
    django_capture_on_commit_callbacks,
):
    for _ in range(2):
        with django_capture_on_commit_callbacks(execute=True):
            call_command("seed_demo_documentos", force=True)

    casos = Tramite.objects.filter(cliente=cliente_demo)
    assert sorted(c.tipo.codigo for c in casos) == sorted(seed.DEMOS)
    for caso in casos:
        assert (caso.estado, caso.motivo.codigo) == ("pendiente", "revision_borrador")
        assert caso.documentos.count() == 1


def test_its_ruts_are_fictitious_and_valid():
    for rut in (seed.RUT_CLIENTE, seed.REPRESENTANTE["rut"], seed.ARRENDADOR["rut"]):
        validate_rut(rut)
