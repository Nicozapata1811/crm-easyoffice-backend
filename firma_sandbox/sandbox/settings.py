"""Settings of the test PSC (PSC de pruebas). Development and tests only."""

import os
from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

from .guard import exigir_ambiente_de_pruebas

AMBIENTE = exigir_ambiente_de_pruebas(os.environ)

env = environ.Env()
BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = env.bool("FIRMA_SANDBOX_DEBUG", default=True)
if not DEBUG and AMBIENTE != "ci":
    msg = "The test signature service runs with DEBUG on outside CI."
    raise ImproperlyConfigured(msg)

SECRET_KEY = env(
    "FIRMA_SANDBOX_SECRET_KEY",
    default="solo-para-pruebas-sin-validez-legal-no-usar-fuera-de-desarrollo",
)
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "firma-sandbox", "testserver"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "rest_framework",
    "drf_spectacular",
    "psc",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "psc.middleware.ApiSoloEnRedInterna",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "sandbox.urls"
WSGI_APPLICATION = "sandbox.wsgi.application"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": ["django.template.context_processors.request"],
        },
    },
]
# The signing page embeds its own PDF.
X_FRAME_OPTIONS = "SAMEORIGIN"

DATA_DIR = Path(env("FIRMA_SANDBOX_DATA_DIR", default=str(BASE_DIR / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "sandbox.sqlite3",
        "OPTIONS": {
            "init_command": "PRAGMA journal_mode=WAL;",
            "transaction_mode": "IMMEDIATE",
        },
    },
}

LANGUAGE_CODE = "es-cl"
TIME_ZONE = "America/Santiago"
USE_I18N = True
USE_TZ = True

DATA_UPLOAD_MAX_MEMORY_SIZE = 15 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 15 * 1024 * 1024

EMAIL_BACKEND = (
    "django.core.mail.backends.locmem.EmailBackend"
    if AMBIENTE == "test"
    else "django.core.mail.backends.smtp.EmailBackend"
)
EMAIL_HOST = env("FIRMA_SANDBOX_EMAIL_HOST", default="mailpit")
EMAIL_PORT = env.int("FIRMA_SANDBOX_EMAIL_PORT", default=1025)
EMAIL_TIMEOUT = 5
DEFAULT_FROM_EMAIL = (
    "PSC de pruebas (sin validez legal) <no-responder@psc-pruebas.test>"
)

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["psc.api.auth.ApiKeyAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["psc.api.auth.EsClienteApi"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "UNAUTHENTICATED_USER": None,
}
SPECTACULAR_SETTINGS = {
    "TITLE": "PSC de pruebas: API de firma electrónica avanzada (sin validez legal)",
    "DESCRIPTION": (
        "Servicio ficticio de certificación para desarrollo y pruebas. Las firmas "
        "que produce no tienen validez legal (Ley 19.799)."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/v1",
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}

# -- The PSC ------------------------------------------------------------------

PKI_DIR = Path(env("FIRMA_SANDBOX_PKI_DIR", default=str(BASE_DIR / ".pki")))
# Encrypts every private key at rest: the CAs', the TSA's and the signers'.
KEY_PASSPHRASE = env(
    "FIRMA_SANDBOX_KEY_PASSPHRASE",
    default="clave-de-pruebas" if AMBIENTE == "test" else None,
)
if not KEY_PASSPHRASE:
    msg = "Set FIRMA_SANDBOX_KEY_PASSPHRASE: it encrypts the test keys at rest."
    raise ImproperlyConfigured(msg)

# Where browsers reach the signing pages and the PKI downloads; certificates
# point their OCSP and CRL addresses here.
PUBLIC_URL = env("FIRMA_SANDBOX_PUBLIC_URL", default="http://localhost:8100").rstrip(
    "/",
)
# Hosts allowed to reach /api/: the compose network only.
API_HOSTS = env.list("FIRMA_SANDBOX_API_HOSTS", default=["firma-sandbox", "testserver"])

OTP_MINUTOS = env.int("FIRMA_SANDBOX_OTP_MINUTOS", default=10)
OTP_INTENTOS = env.int("FIRMA_SANDBOX_OTP_INTENTOS", default=5)
IDENTIDAD_INTENTOS = env.int("FIRMA_SANDBOX_IDENTIDAD_INTENTOS", default=3)
CERTIFICADO_DIAS = 7
SOLICITUD_DIAS_POR_DEFECTO = 7
IDENTITY_VERIFIER = "psc.identidad.RegistroFicticio"

WEBHOOK_BACKOFF_SEGUNDOS = [30, 120, 600, 3600, 21600]
WEBHOOK_BACKOFF_FACTOR = env.float("FIRMA_SANDBOX_BACKOFF_FACTOR", default=1.0)
WEBHOOK_MAX_INTENTOS = 8
WEBHOOK_TIMEOUT_SEGUNDOS = 10
