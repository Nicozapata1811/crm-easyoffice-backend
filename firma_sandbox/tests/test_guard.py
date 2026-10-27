import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured

from sandbox.guard import exigir_ambiente_de_pruebas

RAIZ = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("ambiente", ["local", "test", "ci"])
def test_development_environments_start(ambiente):
    assert (
        exigir_ambiente_de_pruebas(
            {"FIRMA_SANDBOX_ENABLED": "true", "FIRMA_SANDBOX_ENV": ambiente},
        )
        == ambiente
    )


@pytest.mark.parametrize(
    "entorno",
    [
        {},
        {"FIRMA_SANDBOX_ENABLED": "false", "FIRMA_SANDBOX_ENV": "local"},
        {"FIRMA_SANDBOX_ENABLED": "true"},
        {"FIRMA_SANDBOX_ENABLED": "true", "FIRMA_SANDBOX_ENV": "production"},
        {"FIRMA_SANDBOX_ENABLED": "true", "FIRMA_SANDBOX_ENV": "staging"},
        {
            "FIRMA_SANDBOX_ENABLED": "true",
            "FIRMA_SANDBOX_ENV": "local",
            "DJANGO_SETTINGS_MODULE": "config.settings.production",
        },
    ],
)
def test_refuses_without_the_flag_or_with_production_settings(entorno):
    with pytest.raises(ImproperlyConfigured):
        exigir_ambiente_de_pruebas(entorno)


def _arrancar(**entorno: str) -> subprocess.CompletedProcess:
    variables = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("FIRMA_SANDBOX", "DJANGO_"))
    }
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "import django; from django.conf import settings; settings.INSTALLED_APPS",
        ],
        cwd=RAIZ,
        env={**variables, "DJANGO_SETTINGS_MODULE": "sandbox.settings", **entorno},
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_service_does_not_start_without_the_flag():
    resultado = _arrancar()
    assert resultado.returncode != 0
    assert "ImproperlyConfigured" in resultado.stderr


def test_the_service_does_not_start_in_production():
    resultado = _arrancar(FIRMA_SANDBOX_ENABLED="true", FIRMA_SANDBOX_ENV="production")
    assert resultado.returncode != 0
    assert "is not allowed" in resultado.stderr


def test_the_service_does_not_start_with_debug_off_outside_ci():
    resultado = _arrancar(
        FIRMA_SANDBOX_ENABLED="true",
        FIRMA_SANDBOX_ENV="local",
        FIRMA_SANDBOX_DEBUG="false",
        FIRMA_SANDBOX_KEY_PASSPHRASE="x",  # noqa: S106 - a test value
    )
    assert resultado.returncode != 0
    assert "DEBUG" in resultado.stderr
