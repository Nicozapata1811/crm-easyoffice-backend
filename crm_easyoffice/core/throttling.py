"""Rate limit for signing in, shared by every sign-in that takes a password."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from rest_framework.throttling import SimpleRateThrottle

if TYPE_CHECKING:
    from django.http import HttpRequest


class IngresoThrottle(SimpleRateThrottle):
    """Limit sign-in attempts per client address (``login`` rate).

    It limits password guessing, and keeps an anonymous client from growing the
    audit log, whose failed sign-in rows can never be deleted. Works on a plain
    ``HttpRequest`` too, so the Django admin's login can use it.
    """

    scope = "login"

    def get_cache_key(self, request: HttpRequest, view: Any) -> str:
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }
