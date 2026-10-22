"""Generating PLT-02 for a warehouse case. Every value here is synthetic."""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING

import pytest

from crm_easyoffice.clientes.models import Empresa
from crm_easyoffice.clientes.tests.factories import PersonaFactory
from crm_easyoffice.documentos.conversion.plt02 import convertir
from crm_easyoffice.documentos.semillas import ORIGEN_PLT02
from crm_easyoffice.documentos.semillas import PLANTILLA_PLT02
from crm_easyoffice.documentos.services import generar
from crm_easyoffice.documentos.tests import verificacion as v
from crm_easyoffice.inmuebles.models import Autorizante
from crm_easyoffice.inmuebles.models import Oficina
from crm_easyoffice.inmuebles.services import guardar_documento_identidad
from crm_easyoffice.inmuebles.tests.factories import PDF
from crm_easyoffice.inmuebles.tests.factories import archivo
from crm_easyoffice.inmuebles.tests.factories import representacion
from crm_easyoffice.tramites.models import Tramite
from crm_easyoffice.tramites.services import iniciar_tramite
from crm_easyoffice.tramites.services import situacion
from crm_easyoffice.tramites.services import tipo_tramite
from crm_easyoffice.tramites.tests.factories import TIPO_BODEGA
from crm_easyoffice.tramites.tests.factories import cliente_empresa
from crm_easyoffice.tramites.tests.factories import datos_bodega
from crm_easyoffice.tramites.tests.factories import preparar_bodega_caso
from crm_easyoffice.users.tests.factories import UserFactory

if TYPE_CHECKING:
    from crm_easyoffice.documentos.models import Documento

pytestmark = pytest.mark.django_db


def iniciar(sucursal, bodega, *, ejecutar, **extra) -> Tramite:
    cliente = cliente_empresa()
    with ejecutar(execute=True):
        tramite = iniciar_tramite(
            tipo_tramite(TIPO_BODEGA),
            cliente,
            datos_bodega(cliente, sucursal, bodega, **extra),
            canal=Tramite.Canal.BACKOFFICE,
            usuario=UserFactory.create(),
        )
    tramite.refresh_from_db()
    return tramite


@pytest.fixture
def inmuebles():
    return preparar_bodega_caso("LF")


@pytest.fixture
def caso(inmuebles, django_capture_on_commit_callbacks):
    sucursal, bodega = inmuebles
    return iniciar(sucursal, bodega, ejecutar=django_capture_on_commit_callbacks)


def docx_de(documento: Documento) -> bytes:
    with documento.archivo_docx.open("rb") as abierto:
        return abierto.read()


def hojas(nodo):
    if isinstance(nodo, dict):
        for hijo in nodo.values():
            yield from hojas(hijo)
    elif isinstance(nodo, list):
        for hijo in nodo:
            yield from hojas(hijo)
    else:
        yield nodo


def test_conversion_reproduces_the_committed_template():
    convertido = convertir(ORIGEN_PLT02.read_bytes())

    assert v.documento(convertido) == v.documento(PLANTILLA_PLT02.read_bytes())


def test_generation_leaves_the_case_for_review(caso):
    assert situacion(caso) == ("pendiente", "revision_borrador")
    documento = caso.documentos.get()
    assert documento.datos_snapshot["plantilla"]["codigo"] == "PLT-02"


def test_every_printed_value_is_in_the_document(caso):
    documento = caso.documentos.get()
    texto = v.texto(docx_de(documento))
    valores = documento.datos_snapshot["valores"]

    faltan = [h for h in hojas(valores) if v.normalizar(str(h)) not in texto]
    assert faltan == []
    assert all(str(h).strip() for h in hojas(valores))


def test_each_part_of_the_document_names_its_source(caso):
    documento = caso.documentos.get()
    fuentes = documento.datos_snapshot["fuentes"]
    sucursal, bodega = (s.inmueble for s in caso.contrato.servicios.order_by("orden"))
    autorizante = Autorizante.objects.get(inmueble=bodega)

    assert fuentes["oficina"] == sucursal.pk
    assert fuentes["bodega"] == bodega.pk
    assert fuentes["autorizante"] == autorizante.pk
    assert fuentes["persona_autorizante"] == autorizante.persona_id
    assert fuentes["contrato"] == caso.contrato_id
    assert len(fuentes["servicios_contratados"]) == 2  # noqa: PLR2004
    assert None not in fuentes.values()


def test_the_authorisation_prints_the_warehouse_and_its_owner(caso):
    documento = caso.documentos.get()
    texto = v.texto(docx_de(documento))
    valores = documento.datos_snapshot["valores"]
    bodega = Oficina.objects.get(pk=documento.datos_snapshot["fuentes"]["bodega"])

    assert "VIENEN A AUTORIZAR POR DOCE (12) MESES A LA EMPRESA" in texto
    assert "POR IGUAL PERÍODO (12 MESES), SALVO" in texto
    assert (
        f"PARA EL USO DE LA BODEGA UBICADA EN CAMINO DE EJEMPLO 500 BODEGA 7 "
        f"COMUNA DE QUILICURA, REGIÓN METROPOLITANA DE SANTIAGO, "
        f"INDIVIDUALIZADA CON EL ROL DE AVALÚO FISCAL N° {bodega.rol_avaluo}, "
        f"de QUILICURA."
    ) in texto
    assert valores["autorizante"]["nombre"] in texto.split("A U T O R I Z A C I Ó N")[1]
    assert "MACUL" not in texto


def test_primero_names_the_branch_then_the_warehouse(caso):
    primero = v.clausula_primero(docx_de(caso.documentos.get()))

    assert re.search(
        r"DOMICILIO TRIBUTARIO en AVENIDA DE EJEMPLO 100 OFICINA 1 comuna de .+; "
        r"BODEGA y en las condiciones",
        primero,
    )


def test_one_row_per_service_and_no_leftovers(caso):
    docx = docx_de(caso.documentos.get())

    assert v.filas_por_tabla(docx) == [3, 3, v.FILAS_TABLA_COMPLEMENTARIA]
    assert v.restos(docx) == []
    assert len(v.imagenes_resueltas(docx)) == 2  # noqa: PLR2004
    assert not re.search(r"<w:(ins|del)[ >]", v.documento(docx))


def test_a_six_month_term_prints_everywhere(
    inmuebles,
    django_capture_on_commit_callbacks,
):
    sucursal, bodega = inmuebles
    tramite = iniciar(
        sucursal,
        bodega,
        ejecutar=django_capture_on_commit_callbacks,
        duracion_meses=6,
    )
    texto = v.texto(docx_de(tramite.documentos.get()))

    assert "AUTORIZAR POR SEIS (6) MESES" in texto
    assert "IGUAL PERÍODO (6 MESES)" in texto


def test_hashes_signers_and_frozen_snapshot(caso):
    documento = caso.documentos.get()
    dueno = Autorizante.objects.get(
        pk=documento.datos_snapshot["fuentes"]["autorizante"],
    ).persona

    assert documento.sha256_docx == hashlib.sha256(docx_de(documento)).hexdigest()
    assert [(f.rol, f.persona_id) for f in documento.firmantes.all()] == [
        ("cliente_representante", caso.contrato.representante.persona_id),
        ("autorizante", dueno.pk),
    ]
    dueno.profesion = "Otra Profesión"
    dueno.save()
    documento.refresh_from_db()
    assert "OTRA PROFESIÓN" not in str(documento.datos_snapshot)


def falla_con(caso_tramite: Tramite, texto: str) -> None:
    Tramite.objects.filter(pk=caso_tramite.pk).update(estado="iniciado", motivo=None)
    assert generar(caso_tramite) is None
    caso_tramite.refresh_from_db()
    assert situacion(caso_tramite) == ("pendiente", "falta_informacion")
    assert texto in caso_tramite.detalle_pendiente


class TestIncompleteDataGivesNoDocument:
    def test_a_warehouse_without_rol(self, caso):
        Oficina.objects.filter(pk=caso.datos["bodega"]).update(
            rol_avaluo="PENDIENTE-X",
        )
        falla_con(caso, "Falta el rol de avalúo.")

    def test_a_warehouse_without_address(self, caso):
        Oficina.objects.filter(pk=caso.datos["bodega"]).update(calle="")
        falla_con(caso, "Falta la dirección (calle y número).")

    def test_a_branch_without_address(self, caso):
        Oficina.objects.filter(pk=caso.datos["sucursal"]).update(numero="")
        falla_con(caso, "Falta la dirección (calle y número).")

    def test_an_owner_that_is_a_company(self, caso):
        Autorizante.objects.update(activo=False)
        firma = representacion(Empresa.objects.create(rut="76000001-9"))
        Autorizante.objects.create(
            inmueble_id=caso.datos["bodega"],
            empresa=firma.empresa,
            representante=firma,
            vigente_desde="2026-01-01",
        )
        falla_con(caso, "debe ser una persona natural (PLT-02)")

    def test_an_owner_missing_civil_data(self, caso):
        autorizante = Autorizante.objects.get(inmueble_id=caso.datos["bodega"])
        persona = autorizante.persona
        persona.nacionalidad = ""
        persona.save()
        falla_con(caso, "Faltan datos del autorizante: nacionalidad.")

    def test_a_card_side_that_is_a_pdf(self, caso):
        autorizante = Autorizante.objects.get(inmueble_id=caso.datos["bodega"])
        guardar_documento_identidad(autorizante, archivo("anverso.pdf", PDF))
        falla_con(caso, "Falta el anverso de la cédula del autorizante")

    def test_a_contract_without_a_warehouse(self, caso):
        caso.contrato.servicios.filter(orden=2).update(inmueble=None)
        falla_con(caso, "El contrato no tiene una bodega.")

    def test_no_partial_document_is_kept(self, caso):
        PersonaFactory.create()
        Oficina.objects.filter(pk=caso.datos["bodega"]).update(calle="")
        falla_con(caso, "Falta la dirección")
        assert caso.documentos.count() == 1
