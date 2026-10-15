"""Property services and identity-card storage. Every value here is synthetic."""

from __future__ import annotations

import importlib
from datetime import date
from pathlib import Path

import pytest
from django.apps import apps
from django.core.exceptions import ValidationError

from crm_easyoffice.core import validators
from crm_easyoffice.core.storage import private_storage
from crm_easyoffice.inmuebles.models import Oficina
from crm_easyoffice.inmuebles.services import abrir_documento_identidad
from crm_easyoffice.inmuebles.services import autorizante_vigente
from crm_easyoffice.inmuebles.services import codigo_sucursal_de
from crm_easyoffice.inmuebles.services import guardar_documento_identidad
from crm_easyoffice.inmuebles.services import sucursales_activas
from crm_easyoffice.inmuebles.tests.factories import JPEG
from crm_easyoffice.inmuebles.tests.factories import PDF
from crm_easyoffice.inmuebles.tests.factories import PNG
from crm_easyoffice.inmuebles.tests.factories import AutorizanteFactory
from crm_easyoffice.inmuebles.tests.factories import OficinaFactory
from crm_easyoffice.inmuebles.tests.factories import archivo

pytestmark = pytest.mark.django_db

seed = importlib.import_module(
    "crm_easyoffice.inmuebles.migrations.0003_seed_sucursales",
)


class TestSucursales:
    def test_seed_creates_three_branches(self):
        sucursales = sucursales_activas()

        assert [oficina.codigo_sucursal for oficina in sucursales] == ["LF", "SA", "VL"]
        assert sucursales.get(codigo_sucursal="SA").comuna == "Algarrobo"

    def test_seed_is_idempotent(self):
        seed.seed_sucursales(apps, None)

        assert Oficina.objects.filter(codigo_sucursal__isnull=False).count() == 3  # noqa: PLR2004

    def test_warehouse_has_no_branch_code(self):
        bodega = OficinaFactory.create(tipo="bodega")

        assert codigo_sucursal_de(bodega.pk) is None
        assert codigo_sucursal_de(sucursales_activas().first().pk) == "LF"


class TestAutorizanteVigente:
    def test_returns_the_authoriser_for_the_date(self):
        inmueble = OficinaFactory.create()
        AutorizanteFactory.create(
            inmueble=inmueble,
            vigente_desde=date(2025, 1, 1),
            vigente_hasta=date(2025, 12, 31),
        )
        actual = AutorizanteFactory.create(
            inmueble=inmueble,
            vigente_desde=date(2026, 1, 1),
        )

        assert autorizante_vigente(inmueble, date(2026, 10, 14)) == actual

    def test_none_before_any_authorisation(self):
        autorizante = AutorizanteFactory.create(vigente_desde=date(2026, 1, 1))

        assert autorizante_vigente(autorizante.inmueble, date(2025, 12, 31)) is None


class TestDocumentoIdentidad:
    @pytest.mark.parametrize(
        ("nombre", "contenido"),
        [("cedula.jpg", JPEG), ("cedula.png", PNG), ("cedula.pdf", PDF)],
    )
    def test_accepts_jpg_png_and_pdf(self, nombre, contenido):
        autorizante = AutorizanteFactory.create()

        guardar_documento_identidad(autorizante, archivo(nombre, contenido))

        with abrir_documento_identidad(autorizante) as documento:
            assert documento.read() == contenido

    def test_identity_card_stored_outside_media_root(self, settings):
        autorizante = AutorizanteFactory.create()

        guardar_documento_identidad(autorizante, archivo())

        ruta = Path(autorizante.documento_identidad.path)
        assert ruta.is_relative_to(settings.PRIVATE_MEDIA_ROOT)
        assert not ruta.is_relative_to(settings.MEDIA_ROOT)

    def test_file_name_reveals_nothing_about_the_owner(self):
        autorizante = AutorizanteFactory.create()

        guardar_documento_identidad(autorizante, archivo("cedula-de-juan.jpg"))

        nombre = autorizante.documento_identidad.name
        assert nombre.startswith("autorizantes/")
        assert "juan" not in nombre
        assert autorizante.persona.rut not in nombre

    def test_private_storage_builds_no_url(self):
        with pytest.raises(NotImplementedError):
            private_storage.url("autorizantes/x.jpg")

    def test_identity_card_rejects_disallowed_type(self):
        autorizante = AutorizanteFactory.create()

        with pytest.raises(ValidationError):
            guardar_documento_identidad(autorizante, archivo("cedula.gif", b"GIF89a"))

        autorizante.refresh_from_db()
        assert not autorizante.documento_identidad

    def test_identity_card_rejects_spoofed_extension(self):
        autorizante = AutorizanteFactory.create()

        with pytest.raises(ValidationError):
            guardar_documento_identidad(
                autorizante,
                archivo("cedula.jpg", b"<script>alert(1)</script>"),
            )

    def test_identity_card_rejects_oversized_file(self, monkeypatch):
        monkeypatch.setattr(validators, "MAX_UPLOAD_BYTES", 10)
        autorizante = AutorizanteFactory.create()

        with pytest.raises(ValidationError):
            guardar_documento_identidad(autorizante, archivo())

    def test_replacing_identity_card_deletes_old_file(
        self,
        django_capture_on_commit_callbacks,
    ):
        autorizante = AutorizanteFactory.create()
        guardar_documento_identidad(autorizante, archivo())
        anterior = autorizante.documento_identidad.name

        with django_capture_on_commit_callbacks(execute=True):
            guardar_documento_identidad(autorizante, archivo("nueva.png", PNG))

        assert not private_storage.exists(anterior)
        assert private_storage.exists(autorizante.documento_identidad.name)

    def test_opening_without_a_card_raises(self):
        with pytest.raises(FileNotFoundError):
            abrir_documento_identidad(AutorizanteFactory.create())
