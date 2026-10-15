from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from crm_easyoffice.users.tests.factories import UserFactory

if TYPE_CHECKING:
    from crm_easyoffice.users.models import User


@pytest.fixture(autouse=True)
def _media_storage(settings, tmpdir, tmp_path_factory) -> None:
    settings.MEDIA_ROOT = tmpdir.strpath
    # A sibling of MEDIA_ROOT, never inside it, as in production.
    settings.PRIVATE_MEDIA_ROOT = str(tmp_path_factory.mktemp("private_media"))


@pytest.fixture
def user(db) -> User:
    return UserFactory.create()
