"""Production's settings, plus the test PSC and Mailpit. Fictitious data only."""

from .production import *  # noqa: F403
from .production import PORTAL_BASE_URL
from .production import SPECTACULAR_SETTINGS
from .production import env

# production.py refuses the test PSC under SIGNATURE_PROVIDER and
# SIGNATURE_API_BASE_URL at import, so the address arrives under other names.
SIGNATURE_PROVIDER = env("STAGING_SIGNATURE_PROVIDER", default="http")
SIGNATURE_API_BASE_URL = env(
    "STAGING_SIGNATURE_API_BASE_URL",
    default="http://firma-sandbox:8100/api/v1/",
)
SIGNATURE_ALLOW_SANDBOX = True

# Celery starts one process per CPU by default; the VM's memory is tight.
CELERY_WORKER_CONCURRENCY = env.int("CELERY_WORKER_CONCURRENCY", default=2)

EMAIL_HOST = env("EMAIL_HOST", default="mailpit")
EMAIL_PORT = 1025

SPECTACULAR_SETTINGS["SERVERS"] = [
    {"url": PORTAL_BASE_URL, "description": "Staging server"},
]
