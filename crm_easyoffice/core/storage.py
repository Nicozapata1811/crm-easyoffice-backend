"""Storage for uploaded files that must never be publicly reachable."""

from __future__ import annotations

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.functional import cached_property


class PrivateFileSystemStorage(FileSystemStorage):
    """Files kept under ``PRIVATE_MEDIA_ROOT``, outside ``MEDIA_ROOT``.

    Production serves ``MEDIA_ROOT`` straight from nginx, so sensitive
    personal data (identity cards, Ley 21.719) lives in a separate volume
    that no web server mounts. Such files have no URL: they are read through
    a view that checks permissions, so ``url()`` refuses to build one and no
    template or admin widget can link to the file directly.
    """

    @cached_property
    def base_location(self):
        return self._value_or_setting(self._location, settings.PRIVATE_MEDIA_ROOT)

    def _clear_cached_properties(self, setting, **kwargs):
        super()._clear_cached_properties(setting, **kwargs)
        if setting == "PRIVATE_MEDIA_ROOT":
            self.__dict__.pop("base_location", None)
            self.__dict__.pop("location", None)

    def url(self, name):
        msg = "Private files have no URL; serve them through a permission-checked view."
        raise NotImplementedError(msg)


private_storage = PrivateFileSystemStorage()


def get_private_storage() -> PrivateFileSystemStorage:
    """Storage for ``FileField(storage=...)``, referenced by migrations."""
    return private_storage
