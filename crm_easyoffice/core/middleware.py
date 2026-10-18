from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib.sessions.middleware import SessionMiddleware

if TYPE_CHECKING:
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
