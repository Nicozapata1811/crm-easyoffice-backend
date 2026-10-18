from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.conf import settings

from crm_easyoffice.core.middleware import AdminSessionMiddleware
from crm_easyoffice.users.tests.factories import UserFactory

if TYPE_CHECKING:
    from django.test import Client

    from crm_easyoffice.users.models import User


@pytest.fixture(autouse=True)
def _media_storage(settings, tmpdir, tmp_path_factory) -> None:
    settings.MEDIA_ROOT = tmpdir.strpath
    # A sibling of MEDIA_ROOT, never inside it, as in production.
    settings.PRIVATE_MEDIA_ROOT = str(tmp_path_factory.mktemp("private_media"))


@pytest.fixture
def user(db) -> User:
    return UserFactory.create()


@pytest.fixture
def admin_client(client: Client, admin_user: User) -> Client:
    """pytest-django's admin_client, signed in to the admin's own cookie too."""
    client.force_login(admin_user)
    session_key = client.cookies[settings.SESSION_COOKIE_NAME].value
    client.cookies[AdminSessionMiddleware.admin_cookie_name()] = session_key
    return client
