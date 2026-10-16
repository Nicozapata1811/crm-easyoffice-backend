"""Which branches the portal may offer for a domicile (PLT-01). Synthetic data."""

from __future__ import annotations

from datetime import date

import pytest
from django.contrib.admin.sites import site
from django.utils.html import strip_tags

from crm_easyoffice.inmuebles.models import Oficina
from crm_easyoffice.inmuebles.services import abrir_documento_identidad
from crm_easyoffice.inmuebles.services import guardar_documento_identidad
from crm_easyoffice.inmuebles.services import problemas_para_domicilio
from crm_easyoffice.inmuebles.services import sucursales_para_domicilio
from crm_easyoffice.inmuebles.tests.factories import PDF
from crm_easyoffice.inmuebles.tests.factories import AutorizanteFactory
from crm_easyoffice.inmuebles.tests.factories import archivo
from crm_easyoffice.inmuebles.tests.factories import png_sintetico
from crm_easyoffice.inmuebles.tests.factories import preparar_sucursal_domicilio

pytestmark = pytest.mark.django_db

HOY = date(2026, 10, 15)


def lf() -> Oficina:
    return Oficina.objects.get(codigo_sucursal="LF")


def test_a_complete_branch_is_offered():
    preparar_sucursal_domicilio("LF")

    assert problemas_para_domicilio(lf(), HOY) == []
    assert [o.codigo_sucursal for o in sucursales_para_domicilio(HOY)] == ["LF"]


def test_seeded_placeholders_are_not_offered():
    problemas = problemas_para_domicilio(lf(), HOY)

    assert "Falta la dirección (calle y número)." in problemas
    assert "Falta el rol de avalúo." in problemas
    assert sucursales_para_domicilio(HOY) == []


def test_a_branch_without_a_current_authoriser_is_rejected():
    autorizante = preparar_sucursal_domicilio("LF")
    autorizante.vigente_hasta = date(2026, 6, 30)
    autorizante.save()

    assert problemas_para_domicilio(lf(), HOY) == [
        "No hay un autorizante vigente al 15-10-2026.",
    ]
    assert sucursales_para_domicilio(HOY) == []


def test_a_person_authoriser_cannot_sign_plt01():
    preparar_sucursal_domicilio("LF").delete()
    AutorizanteFactory.create(inmueble=lf(), vigente_desde=date(2026, 1, 1))

    assert problemas_para_domicilio(lf(), HOY) == [
        "El autorizante debe ser una empresa con su representante legal (PLT-01).",
    ]


def test_missing_representative_data_is_named():
    autorizante = preparar_sucursal_domicilio("LF")
    persona = autorizante.representante.persona
    persona.profesion = ""
    persona.estado_civil = ""
    persona.save()

    assert problemas_para_domicilio(lf(), HOY) == [
        "Faltan datos del representante del autorizante: estado civil, profesión.",
    ]


def test_both_card_sides_must_be_images():
    autorizante = preparar_sucursal_domicilio("LF")
    guardar_documento_identidad(autorizante, archivo("cedula.pdf", PDF))
    autorizante.documento_identidad_reverso = ""
    autorizante.save()

    assert problemas_para_domicilio(lf(), HOY) == [
        "Falta el anverso de la cédula del autorizante (JPG o PNG).",
        "Falta el reverso de la cédula del autorizante (JPG o PNG).",
    ]


def test_the_sii_unit_and_municipality_are_required():
    preparar_sucursal_domicilio("LF")
    Oficina.objects.filter(codigo_sucursal="LF").update(unidad_sii="", municipalidad="")

    assert problemas_para_domicilio(lf(), HOY) == [
        "Falta la unidad del SII que nombra la autorización.",
        "Falta la municipalidad que nombra la autorización.",
    ]


def test_the_back_side_is_stored_and_read_apart():
    autorizante = preparar_sucursal_domicilio("LF")
    reverso = png_sintetico(tono=10)
    guardar_documento_identidad(autorizante, archivo("r.png", reverso), reverso=True)

    with abrir_documento_identidad(autorizante, reverso=True) as leido:
        assert leido.read() == reverso
    with abrir_documento_identidad(autorizante) as anverso:
        assert anverso.read() != reverso


def test_the_admin_lists_what_is_missing():
    admin = site._registry[Oficina]  # noqa: SLF001

    pendiente = strip_tags(admin.problemas_domicilio(lf()))

    assert "Falta el rol de avalúo." in pendiente
    assert admin.lista_para_domicilio(lf()) is False
