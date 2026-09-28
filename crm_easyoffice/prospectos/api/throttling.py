from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle


class WebhookSitioThrottle(SimpleRateThrottle):
    """Per-IP limit for the website webhook.

    Every real submission comes from the WordPress server, so in practice this
    caps the whole site rather than each visitor.
    """

    scope = "webhook_sitio"

    def get_rate(self) -> str:
        return settings.WEBHOOK_SITIO_THROTTLE_RATE

    def get_cache_key(self, request, view) -> str:
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }
