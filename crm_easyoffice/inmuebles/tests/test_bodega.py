"""Which warehouses an executive may choose for PLT-02. Synthetic data."""

from __future__ import annotations

from datetime import date

import pytest
from django.contrib.admin.sites import site
from django.core.management import call_command
from django.utils.html import strip_tags

from crm_easyoffice.inmuebles.models import Autorizante
from crm_easyoffice.inmuebles.models import Oficina
from crm_easyoffice.inmuebles.models import TipoInmueble
from crm_easyoffice.inmuebles.services import guardar_documento_identidad
from crm_easyoffice.inmuebles.services import inmueble_de
from crm_easyoffice.inmuebles.services import inmuebles_para
from crm_easyoffice.inmuebles.services import problemas_inmueble
from crm_easyoffice.inmuebles.services import problemas_para_bodega
from crm_easyoffice.inmuebles.services import problemas_para_ubicar
from crm_easyoffice.inmuebles.tests.factories import PDF
from crm_easyoffice.inmuebles.tests.factories import archivo
from crm_easyoffice.inmuebles.tests.factories import preparar_bodega
from crm_easyoffice.inmuebles.tests.factories import representacion

pytestmark = pytest.mark.django_db

HOY = date(2026, 10, 20)


def test_a_complete_warehouse_is_offered():
    bodega = preparar_bodega().inmueble

    assert problemas_para_bodega(bodega, HOY) == []
    assert inmuebles_para("bodega", HOY, "bodega") == [bodega]


def test_branches_are_never_warehouses():
    bodega = preparar_bodega().inmueble
    lf = Oficina.objects.get(codigo_sucursal="LF")
    lf.calle, lf.numero = "Avenida de Ejemplo", "10"
    lf.save()

    assert inmuebles_para("sucursal", HOY, "ubicacion") == [lf]
    assert inmueble_de("bodega", lf.pk) is None
    assert inmueble_de("sucursal", bodega.pk) is None


def test_a_warehouse_needs_its_address_and_rol():
    bodega = preparar_bodega(rol_avaluo="PENDIENTE-B1").inmueble
    Oficina.objects.filter(pk=bodega.pk).update(calle="", comuna="")
    bodega.refresh_from_db()

    assert problemas_para_bodega(bodega, HOY) == [
        "Falta la dirección (calle y número).",
        "Falta la comuna o la región.",
        "Falta el rol de avalúo.",
    ]
    assert inmuebles_para("bodega", HOY, "bodega") == []


def test_a_company_owner_cannot_sign_plt02():
    bodega = preparar_bodega().inmueble
    Autorizante.objects.update(activo=False)
    firma = representacion()
    Autorizante.objects.create(
        inmueble=bodega,
        empresa=firma.empresa,
        representante=firma,
        vigente_desde=date(2026, 2, 1),
    )

    assert problemas_para_bodega(bodega, HOY) == [
        "El autorizante de una bodega debe ser una persona natural (PLT-02).",
    ]


def test_missing_owner_data_and_cards_are_named():
    autorizante = preparar_bodega()
    persona = autorizante.persona
    persona.estado_civil = ""
    persona.profesion = ""
    persona.save()
    guardar_documento_identidad(autorizante, archivo("reverso.pdf", PDF), reverso=True)

    assert problemas_para_bodega(autorizante.inmueble, HOY) == [
        "Faltan datos del autorizante: estado civil, profesión.",
        "Falta el reverso de la cédula del autorizante (JPG o PNG).",
    ]


def test_an_owner_not_yet_in_force_does_not_count():
    bodega = preparar_bodega(desde=date(2026, 12, 1)).inmueble

    assert problemas_para_bodega(bodega, HOY) == [
        "No hay un autorizante vigente al 20-10-2026.",
    ]


def test_naming_a_branch_needs_only_its_location():
    lf = Oficina.objects.get(codigo_sucursal="LF")
    lf.calle, lf.numero = "Avenida de Ejemplo", "10"
    lf.save()

    assert problemas_para_ubicar(lf, HOY) == []
    assert problemas_inmueble(lf, HOY, "domicilio") != []


def test_listing_checks_every_owner_in_a_fixed_number_of_queries(
    django_assert_num_queries,
):
    for _ in range(4):
        preparar_bodega()

    with django_assert_num_queries(2):
        assert len(inmuebles_para("bodega", HOY, "bodega")) == 4  # noqa: PLR2004


def test_the_admin_lists_what_a_warehouse_lacks():
    admin = site._registry[Oficina]  # noqa: SLF001
    bodega = preparar_bodega(rol_avaluo="PENDIENTE-B2").inmueble

    assert "Falta el rol de avalúo." in strip_tags(admin.problemas_bodega(bodega))
    assert admin.lista_para_bodega(bodega) is False
    assert admin.lista_para_bodega(Oficina.objects.get(codigo_sucursal="LF")) is None


def test_the_demo_seed_makes_warehouses_ready(settings):
    settings.DEBUG = True

    call_command("seed_demo_bodega")
    call_command("seed_demo_bodega")

    assert len(inmuebles_para("bodega", HOY, "bodega")) == 2  # noqa: PLR2004
    assert Oficina.objects.filter(tipo=TipoInmueble.BODEGA).count() == 2  # noqa: PLR2004
