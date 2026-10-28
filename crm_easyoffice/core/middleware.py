from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib.sessions.middleware import SessionMiddleware

from crm_easyoffice.core.auditoria.contexto import Contexto
from crm_easyoffice.core.auditoria.contexto import contexto_auditoria

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest
    from django.http import HttpResponse


class AdminSessionMiddleware(SessionMiddleware):
    """Give the Django admin its own session cookie.

    Cookies ignore the port, so the web app and the admin would otherwise share
    one session: signing in to either replaced the user of the other. Admin
    requests see their cookie under the default name, so the parent class runs
    unchanged, and the cookie it sets is renamed and scoped to the admin path.
    """

    def process_request(self, request: HttpRequest) -> None:
        if self._is_admin(request):
            cookies = dict(request.COOKIES)
            cookies.pop(settings.SESSION_COOKIE_NAME, None)
            admin_key = cookies.pop(self.admin_cookie_name(), None)
            if admin_key is not None:
                cookies[settings.SESSION_COOKIE_NAME] = admin_key
            request.COOKIES = cookies
        super().process_request(request)

    def process_response(
        self,
        request: HttpRequest,
        response: HttpResponse,
    ) -> HttpResponse:
        response = super().process_response(request, response)
        if self._is_admin(request) and settings.SESSION_COOKIE_NAME in response.cookies:
            name = self.admin_cookie_name()
            morsel = response.cookies.pop(settings.SESSION_COOKIE_NAME)
            morsel.set(name, morsel.value, morsel.coded_value)
            morsel["path"] = self.admin_path()
            response.cookies[name] = morsel
        return response

    @staticmethod
    def admin_cookie_name() -> str:
        return f"{settings.SESSION_COOKIE_NAME}_admin"

    @staticmethod
    def admin_path() -> str:
        return f"/{settings.ADMIN_URL}"

    def _is_admin(self, request: HttpRequest) -> bool:
        return request.path_info.startswith(self.admin_path())


class AuditoriaMiddleware:
    """Make the request the audit context while it runs (RF-15).

    It sets nothing in the database: ``core.auditoria.contexto`` does, before
    the first write of the request's transaction, which this middleware does
    not see (``ATOMIC_REQUESTS`` wraps only the view).
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        with contexto_auditoria(Contexto(request=request)):
            return self.get_response(request)
