"""The issuer's configuration. Every value here is synthetic."""

from __future__ import annotations

import importlib
from http import HTTPStatus

import pytest
from django.contrib.auth.models import Group
from django.db import IntegrityError
from django.urls import reverse

from crm_easyoffice.configuracion.models import ConfigEmpresa
from crm_easyoffice.configuracion.models import Marca
from crm_easyoffice.configuracion.services import ConfiguracionIncompletaError
from crm_easyoffice.configuracion.services import cuenta_pago_para
from crm_easyoffice.configuracion.services import marcas_activas
from crm_easyoffice.configuracion.services import obtener_config_empresa
from crm_easyoffice.configuracion.tests.factories import CuentaPagoFactory
from crm_easyoffice.configuracion.tests.factories import MarcaFactory
from crm_easyoffice.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

roles = importlib.import_module("crm_easyoffice.core.migrations.0002_seed_roles")


class TestSeed:
    def test_seed_creates_two_brands_with_fictitious_accounts(self):
        marcas = Marca.objects.select_related("cuenta_pago_default")

        assert [marca.nombre for marca in marcas] == ["EASY OFFICE", "INOFFICE"]
        for marca in marcas:
            assert marca.cuenta_pago_default.banco == "Banco de Ejemplo"
            assert "EJEMPLO" in marca.cuenta_pago_default.texto_contrato

    def test_seed_invents_no_rut(self):
        config = obtener_config_empresa()

        assert config.razon_social == "Easy Office SpA"
        assert config.rut == ""
        assert config.registro_personeria.endswith("Ley 20.659")


class TestConfigEmpresa:
    def test_config_empresa_is_singleton(self):
        with pytest.raises(IntegrityError):
            ConfigEmpresa.objects.create(razon_social="Otra Empresa de Ejemplo SpA")

    def test_obtener_config_raises_when_missing(self):
        ConfigEmpresa.objects.all().delete()

        with pytest.raises(ConfiguracionIncompletaError):
            obtener_config_empresa()


class TestCuentaPago:
    def test_cuenta_pago_defaults_to_brand_account(self):
        marca = MarcaFactory.create()

        assert cuenta_pago_para(marca) == marca.cuenta_pago_default

    def test_explicit_account_wins(self):
        marca = MarcaFactory.create()
        otra = CuentaPagoFactory.create()

        assert cuenta_pago_para(marca, otra) == otra

    def test_inactive_account_is_rejected(self):
        marca = MarcaFactory.create(cuenta_pago_default__activa=False)

        with pytest.raises(ConfiguracionIncompletaError):
            cuenta_pago_para(marca)

    def test_brand_without_account_is_rejected(self):
        with pytest.raises(ConfiguracionIncompletaError):
            cuenta_pago_para(MarcaFactory.create(cuenta_pago_default=None))

    def test_inactive_brands_are_not_offered(self):
        MarcaFactory.create(nombre="MARCA INACTIVA", activa=False)

        assert "MARCA INACTIVA" not in {marca.nombre for marca in marcas_activas()}


class TestPermisos:
    def _usuario(self, rol: str):
        user = UserFactory.create()
        user.groups.add(Group.objects.get(name=rol))
        return user

    def test_ejecutivo_can_only_view_configuracion(self):
        ejecutivo = self._usuario(roles.EJECUTIVO)

        assert ejecutivo.has_perm("configuracion.view_marca")
        assert ejecutivo.has_perm("configuracion.view_cuentapago")
        assert not ejecutivo.has_perm("configuracion.change_marca")
        assert not ejecutivo.has_perm("configuracion.change_configempresa")

    def test_nobody_deletes_configuracion(self):
        administrador = self._usuario(roles.ADMINISTRADOR)

        assert administrador.has_perm("configuracion.change_configempresa")
        assert not administrador.has_perm("configuracion.delete_marca")
        assert not administrador.has_perm("configuracion.delete_cuentapago")


class TestAdmin:
    def test_a_second_company_record_cannot_be_added(self, admin_client):
        response = admin_client.get(reverse("admin:configuracion_configempresa_add"))

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_company_record_can_be_edited(self, admin_client):
        config = obtener_config_empresa()

        response = admin_client.get(
            reverse("admin:configuracion_configempresa_change", args=[config.pk]),
        )

        assert response.status_code == HTTPStatus.OK
