from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.http import HttpResponseNotFound

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest
    from django.http import HttpResponse


class ApiSoloEnRedInterna:
    """Serve ``/api/`` only to hosts on the compose network.

    The port is published for the signing pages, which browsers open; the
    API is for the client systems, which reach the service by its compose
    name, as they would reach a provider's private endpoint.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if (
            request.path.startswith("/api/")
            and request.get_host().split(":")[0] not in settings.API_HOSTS
        ):
            return HttpResponseNotFound()
        return self.get_response(request)
