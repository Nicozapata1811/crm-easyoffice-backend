"""Generating PLT-01 for a domicile case. Every value here is synthetic."""

from __future__ import annotations

import hashlib

import pytest

from crm_easyoffice.documentos.conversion.plt01 import convertir
from crm_easyoffice.documentos.models import Documento
from crm_easyoffice.documentos.models import PlantillaDocumentoError
from crm_easyoffice.documentos.semillas import ORIGEN_PLT01
from crm_easyoffice.documentos.semillas import PLANTILLA_PLT01
from crm_easyoffice.documentos.services import generar
from crm_easyoffice.documentos.tests import verificacion as v
from crm_easyoffice.inmuebles.models import Autorizante
from crm_easyoffice.tramites.services import actualizar_domicilio
from crm_easyoffice.tramites.services import iniciar_domicilio
from crm_easyoffice.tramites.services import situacion
from crm_easyoffice.tramites.tests.factories import cuenta_empresa
from crm_easyoffice.tramites.tests.factories import datos_domicilio
from crm_easyoffice.tramites.tests.factories import preparar_domicilio

pytestmark = pytest.mark.django_db


@pytest.fixture
def caso(django_capture_on_commit_callbacks):
    sucursal = preparar_domicilio("LF")
    cliente = cuenta_empresa().cliente
    with django_capture_on_commit_callbacks(execute=True):
        tramite = iniciar_domicilio(cliente, datos_domicilio(cliente, sucursal))
    tramite.refresh_from_db()
    return tramite


def docx_de(documento: Documento) -> bytes:
    with documento.archivo_docx.open("rb") as archivo:
        return archivo.read()


def test_conversion_reproduces_the_committed_template():
    convertido = convertir(ORIGEN_PLT01.read_bytes())

    assert v.documento(convertido) == v.documento(PLANTILLA_PLT01.read_bytes())


def test_generation_leaves_the_case_for_review(caso):
    assert situacion(caso) == ("pendiente", "revision_borrador")
    assert caso.documentos.count() == 1


def test_every_merge_field_is_filled_from_its_source(caso):
    documento = caso.documentos.get()
    texto = v.texto(docx_de(documento))
    valores = documento.datos_snapshot["valores"]

    def hojas(nodo):
        if isinstance(nodo, dict):
            for hijo in nodo.values():
                yield from hojas(hijo)
        elif isinstance(nodo, list):
            for hijo in nodo:
                yield from hojas(hijo)
        else:
            yield nodo

    faltan = [
        valor for valor in hojas(valores) if v.normalizar(str(valor)) not in texto
    ]
    assert faltan == []
    assert caso.contrato.folio in texto
    assert valores["empresa"]["rut"].count(".") == 2  # noqa: PLR2004


def test_no_field_tag_or_placeholder_is_left(caso):
    assert v.restos(docx_de(caso.documentos.get())) == []


def test_empty_service_rows_are_removed(caso):
    docx = docx_de(caso.documentos.get())

    assert v.filas_por_tabla(docx) == [2, 2, v.FILAS_TABLA_COMPLEMENTARIA]
    primero = v.clausula_primero(docx)
    assert ";" not in primero.split("y en las condiciones")[0][-40:]


def test_both_card_images_are_embedded_and_namespaces_kept(caso):
    docx = docx_de(caso.documentos.get())

    assert len(v.imagenes_resueltas(docx)) == 2  # noqa: PLR2004
    assert v.espacios_de_nombres(v.documento(docx)) == v.espacios_de_nombres(
        v.documento(PLANTILLA_PLT01.read_bytes()),
    )


def test_hashes_snapshot_signers_and_template_version(caso):
    documento = caso.documentos.get()

    assert documento.sha256_docx == hashlib.sha256(docx_de(documento)).hexdigest()
    assert documento.datos_snapshot["plantilla"]["codigo"] == "PLT-01"
    assert documento.datos_snapshot["fuentes"]["contrato"] == caso.contrato_id
    assert [f.rol for f in documento.firmantes.all()] == [
        "cliente_representante",
        "autorizante",
    ]
    with pytest.raises(PlantillaDocumentoError):
        documento.version_plantilla.save()


def test_the_snapshot_is_frozen(caso):
    documento = caso.documentos.get()
    persona = caso.contrato.representante.persona
    persona.domicilio = "Otra Dirección 999"
    persona.save()

    documento.refresh_from_db()
    assert "OTRA DIRECCIÓN" not in str(documento.datos_snapshot)


def test_editing_generates_a_new_version(caso, django_capture_on_commit_callbacks):
    cliente = caso.cliente
    sucursal_id = caso.datos["sucursal"]
    from crm_easyoffice.inmuebles.models import Oficina  # noqa: PLC0415

    sucursal = Oficina.objects.get(pk=sucursal_id)
    with django_capture_on_commit_callbacks(execute=True):
        actualizar_domicilio(caso, datos_domicilio(cliente, sucursal, plan="semestral"))

    versiones = list(
        caso.documentos.order_by("version").values_list("version", "estado"),
    )
    assert versiones == [(1, "reemplazado"), (2, "generado")]


def test_a_branch_without_authoriser_gives_no_document(
    django_capture_on_commit_callbacks,
):
    sucursal = preparar_domicilio("LF")
    cliente = cuenta_empresa().cliente
    tramite = iniciar_domicilio(cliente, datos_domicilio(cliente, sucursal))
    Autorizante.objects.update(activo=False)

    assert generar(tramite) is None

    tramite.refresh_from_db()
    assert situacion(tramite) == ("pendiente", "falta_informacion")
    assert "autorizante" in tramite.detalle_pendiente
    assert not Documento.objects.exists()


def test_the_template_carries_no_tracked_changes(caso):
    import re  # noqa: PLC0415

    for docx in (PLANTILLA_PLT01.read_bytes(), docx_de(caso.documentos.get())):
        assert not re.search(r"<w:(ins|del)[ >]", v.documento(docx))
