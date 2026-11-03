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


def _importar_settings(modulo: str, **entorno: str) -> subprocess.CompletedProcess:
    variables = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("DJANGO_", "SIGNATURE_", "STAGING_"))
    }
    codigo = (
        f"from {modulo} import SIGNATURE_ALLOW_SANDBOX, SIGNATURE_API_BASE_URL, "
        "SIGNATURE_PROVIDER; "
        "print(SIGNATURE_PROVIDER, SIGNATURE_API_BASE_URL, SIGNATURE_ALLOW_SANDBOX)"
    )
    return subprocess.run(  # noqa: S603 - our own code, in a test
        [sys.executable, "-c", codigo],
        cwd=RAIZ,
        env={
            **variables,
            "DJANGO_SECRET_KEY": "x" * 50,
            "DJANGO_ADMIN_URL": "admin/",
            **entorno,
        },
        capture_output=True,
        text=True,
        check=False,
    )


def test_staging_settings_accept_the_test_psc():
    resultado = _importar_settings("config.settings.staging")
    assert resultado.returncode == 0, resultado.stderr
    assert resultado.stdout.split() == [
        "http",
        "http://firma-sandbox:8100/api/v1/",
        "True",
    ]


def test_staging_settings_refuse_the_test_psc_under_the_production_names():
    resultado = _importar_settings(
        "config.settings.staging",
        SIGNATURE_PROVIDER="http",
        SIGNATURE_API_BASE_URL="http://firma-sandbox:8100/api/v1/",
    )
    assert resultado.returncode != 0
    assert "test signature service" in resultado.stderr


def test_production_settings_ignore_the_staging_variables():
    resultado = _importar_settings(
        "config.settings.production",
        STAGING_SIGNATURE_PROVIDER="http",
        STAGING_SIGNATURE_API_BASE_URL="http://firma-sandbox:8100/api/v1/",
    )
    assert resultado.returncode == 0, resultado.stderr
    assert resultado.stdout.split() == ["simulated", "False"]


def test_staging_urls_never_point_at_localhost():
    plantillas = RAIZ / ".envs.example" / ".staging"
    urls = [
        linea
        for archivo in plantillas.iterdir()
        for linea in archivo.read_text().splitlines()
        if "://" in linea and not linea.startswith("#")
    ]
    assert urls
    assert not [url for url in urls if "localhost" in url or "127.0.0.1" in url]


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
