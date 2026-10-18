"""All data here is synthetic."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse

from crm_easyoffice.clientes.tests.factories import CuentaClienteFactory
from crm_easyoffice.core.middleware import AdminSessionMiddleware
from crm_easyoffice.users.tests.factories import UserFactory

if TYPE_CHECKING:
    from crm_easyoffice.users.models import User

PASSWORD = "synthetic-Pass-123"  # noqa: S105
ADMIN_COOKIE = AdminSessionMiddleware.admin_cookie_name()


@pytest.fixture
def browser() -> Client:
    return Client(enforce_csrf_checks=False)


@pytest.fixture
def cliente(db) -> User:
    return CuentaClienteFactory.create(user__password=PASSWORD).user


@pytest.fixture
def superusuario(db) -> User:
    return UserFactory.create(password=PASSWORD, is_staff=True, is_superuser=True)


def web_login(browser: Client, user: User):
    return browser.post(
        reverse("auth:login"),
        {"email": user.email, "password": PASSWORD},
        content_type="application/json",
    )


def admin_login(browser: Client, user: User):
    return browser.post(
        reverse("admin:login"),
        {"username": user.email, "password": PASSWORD, "next": reverse("admin:index")},
    )


def web_user_email(browser: Client) -> str | None:
    response = browser.get(reverse("auth:me"))
    return response.json()["email"] if response.status_code == HTTPStatus.OK else None


def admin_is_signed_in(browser: Client) -> bool:
    return browser.get(reverse("admin:index")).status_code == HTTPStatus.OK


class TestAdminSession:
    def test_admin_login_keeps_the_web_session(self, browser, cliente, superusuario):
        web_login(browser, cliente)
        admin_login(browser, superusuario)

        assert web_user_email(browser) == cliente.email
        assert admin_is_signed_in(browser)

    def test_web_login_keeps_the_admin_session(self, browser, cliente, superusuario):
        admin_login(browser, superusuario)
        web_login(browser, cliente)

        assert admin_is_signed_in(browser)
        assert web_user_email(browser) == cliente.email

    def test_web_session_does_not_sign_in_to_the_admin(self, browser, superusuario):
        web_login(browser, superusuario)

        assert web_user_email(browser) == superusuario.email
        assert not admin_is_signed_in(browser)

    def test_admin_logout_keeps_the_web_session(self, browser, cliente, superusuario):
        web_login(browser, cliente)
        admin_login(browser, superusuario)

        browser.post(reverse("admin:logout"))

        assert not admin_is_signed_in(browser)
        assert web_user_email(browser) == cliente.email

    def test_admin_cookie_is_scoped_to_the_admin(self, browser, superusuario):
        response = admin_login(browser, superusuario)

        assert settings.SESSION_COOKIE_NAME not in response.cookies
        cookie = response.cookies[ADMIN_COOKIE]
        assert cookie["path"] == f"/{settings.ADMIN_URL}"
        assert cookie["httponly"] is True
