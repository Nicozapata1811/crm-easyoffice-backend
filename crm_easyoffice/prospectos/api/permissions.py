from django.conf import settings
from django.utils.crypto import constant_time_compare
from rest_framework.permissions import BasePermission


class WebhookSitioTokenPermission(BasePermission):
    """Shared secret in the ``token`` query parameter.

    It travels in the URL because not every form builder can set headers. An
    unset ``WEBHOOK_SITIO_TOKEN`` rejects every request.
    """

    def has_permission(self, request, view) -> bool:
        expected = settings.WEBHOOK_SITIO_TOKEN
        provided = request.query_params.get("token", "")
        return bool(expected) and constant_time_compare(provided, expected)
