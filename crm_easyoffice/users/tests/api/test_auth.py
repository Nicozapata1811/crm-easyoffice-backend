from __future__ import annotations

import importlib
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest
from django.conf import settings
from django.contrib.auth.models import Group
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.urls import reverse
from rest_framework.test import APIClient

from crm_easyoffice.users.forms import UserAdminChangeForm
from crm_easyoffice.users.tests.factories import UserFactory

if TYPE_CHECKING:
    from crm_easyoffice.users.models import User

PASSWORD = "synthetic-Pass-123"  # noqa: S105

seed = importlib.import_module("crm_easyoffice.core.migrations.0002_seed_roles")


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def administrador(db) -> User:
    user = UserFactory.create(password=PASSWORD)
    user.groups.add(Group.objects.get(name=seed.ADMINISTRADOR))
    return user


def login(client: APIClient, email: str, password: str = PASSWORD):
    return client.post(
        reverse("auth:login"),
        {"email": email, "password": password},
        format="json",
    )


class TestLogin:
    def test_valid_credentials_start_a_session(self, api_client, administrador):
        response = login(api_client, administrador.email)

        assert response.status_code == HTTPStatus.OK
        assert response.data["email"] == administrador.email
        assert api_client.get(reverse("auth:me")).status_code == HTTPStatus.OK

    def test_session_cookie_is_httponly(self, api_client, administrador):
        response = login(api_client, administrador.email)

        assert response.cookies[settings.SESSION_COOKIE_NAME]["httponly"] is True

    def test_invalid_credentials_do_not_reveal_whether_the_user_exists(
        self,
        api_client,
        administrador,
    ):
        wrong_password = login(api_client, administrador.email, "not-the-password")
        unknown_email = login(api_client, "nobody@example.com")

        assert wrong_password.status_code == HTTPStatus.BAD_REQUEST
        assert unknown_email.status_code == wrong_password.status_code
        assert unknown_email.data == wrong_password.data
        assert settings.SESSION_COOKIE_NAME not in wrong_password.cookies

    def test_inactive_user_gets_the_same_answer(self, api_client, administrador):
        administrador.is_active = False
        administrador.save()

        response = login(api_client, administrador.email)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.data == login(api_client, "nobody@example.com").data

    def test_login_requires_a_csrf_token(self, administrador):
        client = APIClient(enforce_csrf_checks=True)

        assert login(client, administrador.email).status_code == HTTPStatus.FORBIDDEN

        token = client.get(reverse("auth:csrf")).data["csrfToken"]
        response = client.post(
            reverse("auth:login"),
            {"email": administrador.email, "password": PASSWORD},
            format="json",
            headers={"X-CSRFToken": token},
        )
        assert response.status_code == HTTPStatus.OK


class TestSession:
    @pytest.mark.django_db
    def test_me_requires_authentication(self, api_client):
        assert api_client.get(reverse("auth:me")).status_code == HTTPStatus.FORBIDDEN

    def test_logout_ends_the_session(self, api_client, administrador):
        login(api_client, administrador.email)

        response = api_client.post(reverse("auth:logout"))

        assert response.status_code == HTTPStatus.NO_CONTENT
        assert api_client.get(reverse("auth:me")).status_code == HTTPStatus.FORBIDDEN

    def test_me_returns_role_and_permissions(self, api_client, administrador):
        api_client.force_authenticate(administrador)

        data = api_client.get(reverse("auth:me")).data

        assert data["rol"] == seed.ADMINISTRADOR
        assert "core.view_dashboard" in data["permisos"]
        assert "password" not in data

    def test_me_without_role(self, api_client, user):
        api_client.force_authenticate(user)

        data = api_client.get(reverse("auth:me")).data

        assert data["rol"] is None
        assert data["permisos"] == []


@pytest.mark.django_db
class TestRoles:
    def test_ejecutivo_cannot_delete_or_see_the_dashboard(self):
        codenames = set(
            Group.objects.get(name=seed.EJECUTIVO).permissions.values_list(
                "codename",
                flat=True,
            ),
        )

        assert codenames
        assert not {c for c in codenames if c.startswith("delete_")}
        assert "view_dashboard" not in codenames
        assert {"add_cliente", "change_cliente", "view_cliente"} <= codenames

    def test_seed_is_idempotent(self):
        before = {
            g.name: g.permissions.count()
            for g in Group.objects.filter(name__in=[seed.ADMINISTRADOR, seed.EJECUTIVO])
        }

        state_apps = MigrationExecutor(connection).loader.project_state().apps
        seed.seed_roles(state_apps, None)

        after = {
            g.name: g.permissions.count()
            for g in Group.objects.filter(name__in=[seed.ADMINISTRADOR, seed.EJECUTIVO])
        }
        assert after == before
        assert len(after) == 2  # noqa: PLR2004

    def test_admin_form_allows_one_role_only(self, user):
        form = UserAdminChangeForm(
            instance=user,
            data={
                "email": user.email,
                "date_joined": user.date_joined,
                "groups": list(Group.objects.values_list("pk", flat=True)),
            },
        )

        assert not form.is_valid()
        assert "groups" in form.errors
