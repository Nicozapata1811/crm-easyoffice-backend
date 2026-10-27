"""Choosing the signature provider, and keeping the test PSC out of production."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from django.core.exceptions import ImproperlyConfigured

from crm_easyoffice.integrations.signature.base import SignatureError
from crm_easyoffice.integrations.signature.base import SignatureResult
from crm_easyoffice.integrations.signature.base import SignatureStatus
from crm_easyoffice.integrations.signature.http import HttpSignatureProvider
from crm_easyoffice.integrations.signature.registry import es_url_de_pruebas
from crm_easyoffice.integrations.signature.registry import exigir_proveedor_real
from crm_easyoffice.integrations.signature.registry import exigir_resultado_admitido
from crm_easyoffice.integrations.signature.registry import get_signature_provider
from crm_easyoffice.integrations.signature.simulated import SimulatedSignatureProvider

RAIZ = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    "url",
    [
        "http://firma-sandbox:8100/api/v1/",
        "http://localhost:8100/api/v1/",
        "http://127.0.0.1:8100/",
        "http://10.0.0.5/api/",
        "https://psc.test/api/",
        "http://algo.localhost/",
    ],
)
def test_production_refuses_the_test_psc_and_development_hosts(url):
    assert es_url_de_pruebas(url)
    with pytest.raises(ImproperlyConfigured):
        exigir_proveedor_real("http", url)


def test_production_accepts_a_public_provider():
    exigir_proveedor_real("http", "https://api.proveedor-acreditado.example.com/v1/")
    exigir_proveedor_real("simulated", "")


def test_production_settings_refuse_to_load_with_the_sandbox_url():
    variables = {k: v for k, v in os.environ.items() if not k.startswith("DJANGO_")}
    resultado = subprocess.run(
        [sys.executable, "-c", "import config.settings.production"],
        cwd=RAIZ,
        env={
            **variables,
            "DJANGO_SECRET_KEY": "x" * 50,
            "DJANGO_ADMIN_URL": "admin/",
            "SIGNATURE_PROVIDER": "http",
            "SIGNATURE_API_BASE_URL": "http://firma-sandbox:8100/api/v1/",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert resultado.returncode != 0
    assert "test signature service" in resultado.stderr


def test_the_registry_builds_the_configured_provider(settings):
    settings.SIGNATURE_PROVIDER = "simulated"
    assert isinstance(get_signature_provider(), SimulatedSignatureProvider)

    settings.SIGNATURE_PROVIDER = "http"
    settings.SIGNATURE_API_BASE_URL = "http://firma-sandbox:8100/api/v1/"
    settings.SIGNATURE_API_KEY = "clave"
    settings.SIGNATURE_WEBHOOK_SECRET = "secreto"  # noqa: S105
    assert isinstance(get_signature_provider(), HttpSignatureProvider)

    settings.SIGNATURE_PROVIDER = "otro"
    with pytest.raises(SignatureError):
        get_signature_provider()


def test_the_sandbox_is_refused_where_it_is_not_allowed(settings):
    settings.SIGNATURE_PROVIDER = "http"
    settings.SIGNATURE_API_BASE_URL = "http://firma-sandbox:8100/api/v1/"
    settings.SIGNATURE_API_KEY = "clave"
    settings.SIGNATURE_WEBHOOK_SECRET = "secreto"  # noqa: S105
    settings.SIGNATURE_ALLOW_SANDBOX = False
    with pytest.raises(SignatureError, match="not allowed"):
        get_signature_provider()

    de_pruebas = SignatureResult("x", SignatureStatus.PENDING, test_environment=True)
    with pytest.raises(SignatureError):
        exigir_resultado_admitido(de_pruebas)


def test_production_compose_has_no_test_psc():
    produccion = yaml.safe_load((RAIZ / "docker-compose.production.yml").read_text())
    assert not [nombre for nombre in produccion["services"] if "firma" in nombre]
    assert "firma_sandbox" not in (RAIZ / "docker-compose.production.yml").read_text()


def test_the_crm_never_imports_the_test_psc():
    """They talk only over HTTP, as with a real provider (ruff bans it too)."""
    importacion = re.compile(r"^\s*(from|import)\s+(firma_sandbox|psc|sandbox)\b", re.M)
    culpables = [
        str(ruta.relative_to(RAIZ))
        for carpeta in ("crm_easyoffice", "config")
        for ruta in (RAIZ / carpeta).rglob("*.py")
        if importacion.search(ruta.read_text())
    ]
    assert culpables == []
