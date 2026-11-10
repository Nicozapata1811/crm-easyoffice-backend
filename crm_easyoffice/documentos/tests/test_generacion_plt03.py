"""Generating PLT-03 for a vehicle-lease case. Every value here is synthetic."""

from __future__ import annotations

import pytest

from crm_easyoffice.clientes.models import Persona
from crm_easyoffice.clientes.models import RepresentanteLegal
from crm_easyoffice.contratos.models import Contrato
from crm_easyoffice.documentos.conversion import ooxml
from crm_easyoffice.documentos.conversion.plt03 import RESTOS
from crm_easyoffice.documentos.conversion.plt03 import convertir
from crm_easyoffice.documentos.models import Firmante
from crm_easyoffice.documentos.semillas import ORIGEN_PLT03
from crm_easyoffice.documentos.semillas import PLANTILLA_PLT03
from crm_easyoffice.documentos.services import firmantes_en_orden
from crm_easyoffice.documentos.services import generar
from crm_easyoffice.documentos.tests import verificacion as v
from crm_easyoffice.documentos.tests.test_generacion_plt02 import docx_de
from crm_easyoffice.documentos.tests.test_generacion_plt02 import hojas
from crm_easyoffice.tramites.models import Tramite
from crm_easyoffice.tramites.services import iniciar_tramite
from crm_easyoffice.tramites.services import reintentar_documento
from crm_easyoffice.tramites.services import situacion
from crm_easyoffice.tramites.services import tipo_tramite
from crm_easyoffice.tramites.tests.factories import RUT_ARRENDADOR
from crm_easyoffice.tramites.tests.factories import RUT_REPRESENTANTE
from crm_easyoffice.tramites.tests.factories import TIPO_VEHICULO
from crm_easyoffice.tramites.tests.factories import cliente_empresa
from crm_easyoffice.tramites.tests.factories import datos_vehiculo
from crm_easyoffice.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def iniciar(*, ejecutar, cliente=None, **extra) -> Tramite:
    cliente = cliente or cliente_empresa()
    with ejecutar(execute=True):
        tramite = iniciar_tramite(
            tipo_tramite(TIPO_VEHICULO),
            cliente,
            datos_vehiculo(cliente, **extra),
            canal=Tramite.Canal.BACKOFFICE,
            usuario=UserFactory.create(),
        )
    tramite.refresh_from_db()
    return tramite


@pytest.fixture
def caso(django_capture_on_commit_callbacks):
    return iniciar(ejecutar=django_capture_on_commit_callbacks)


def test_conversion_reproduces_the_committed_template():
    convertido = convertir(ORIGEN_PLT03.read_bytes())

    assert v.documento(convertido) == v.documento(PLANTILLA_PLT03.read_bytes())


def test_conversion_leaves_no_marker_or_labelled_blank():
    texto = ooxml.text(v.documento(PLANTILLA_PLT03.read_bytes()))

    assert "[" not in texto
    assert ": _" not in texto
    # The two bare lines stay: they are where each party signs.
    assert texto.count("____________________________") == 2  # noqa: PLR2004


def test_a_marker_without_a_source_fails_the_conversion():
    origen = ooxml.read_docx(ORIGEN_PLT03.read_bytes())
    doc = origen["word/document.xml"].decode().replace("[COLOR]", "[TONO]")
    origen["word/document.xml"] = doc.encode()

    with pytest.raises(KeyError, match="TONO"):
        convertir(ooxml.write_docx(origen))


def test_the_leftover_patterns_catch_each_placeholder_kind():
    import re  # noqa: PLC0415

    assert all(
        any(re.search(patron, resto) for patron in RESTOS)
        for resto in ("En [COMUNA], a", "Nombre: ________")
    )


def test_generation_leaves_the_case_for_review_without_a_contract(caso):
    assert situacion(caso) == ("pendiente", "revision_borrador")
    assert caso.contrato is None
    assert not Contrato.objects.exists()
    documento = caso.documentos.get()
    assert documento.datos_snapshot["plantilla"]["codigo"] == "PLT-03"
    assert documento.archivo_docx
    assert documento.archivo_pdf


def test_every_printed_value_is_in_the_document_and_nothing_is_left(caso):
    documento = caso.documentos.get()
    docx = docx_de(documento)
    texto = v.texto(docx)
    valores = documento.datos_snapshot["valores"]

    faltan = [h for h in hojas(valores) if v.normalizar(str(h)) not in texto]
    assert faltan == []
    assert all(str(h).strip() for h in hojas(valores))
    assert v.restos(docx) == []
    assert "[" not in texto
    assert ": _" not in texto


def test_the_lease_prints_its_parties_vehicle_and_terms(caso):
    valores = caso.documentos.get().datos_snapshot["valores"]

    assert valores["arrendador"] == {
        "nombre": "RODRIGO IGNACIO INVENTADO FICTICIO",
        "rut": "32.333.444-" + RUT_ARRENDADOR[-1],
        "domicilio": "AVENIDA IMAGINARIA 456, LA FLORIDA",
    }
    assert valores["empresa"]["razon_social"] == "Comercial Ficticia del Sur SpA"
    assert valores["empresa"]["domicilio"] == "CALLE SUPUESTA 789, OFICINA 12"
    assert valores["representante"]["nombre"] == "CAMILA ANDREA EJEMPLO PRUEBA"
    assert valores["vehiculo"]["patente"] == "BBDF12"
    assert valores["plazo"] == "DOCE (12) MESES"
    # RN-37: start + term - 1 day.
    assert valores["fecha_inicio"] == "02 DE OCTUBRE DE 2026"
    assert valores["fecha_termino"] == "01 DE OCTUBRE DE 2027"
    assert (valores["renta"], valores["renta_letras"]) == (
        "250.000",
        "DOSCIENTOS CINCUENTA MIL",
    )
    assert (valores["dia_pago"], valores["medio_pago"]) == (
        "5",
        "transferencia bancaria",
    )
    assert "folio" not in valores


def test_another_payment_method_prints_as_typed(django_capture_on_commit_callbacks):
    caso = iniciar(
        ejecutar=django_capture_on_commit_callbacks,
        medio_pago="otro",
        medio_pago_otro="vale vista",
    )

    valores = caso.documentos.get().datos_snapshot["valores"]
    assert valores["medio_pago"] == "vale vista"


def test_each_part_of_the_document_names_its_source(caso):
    fuentes = caso.documentos.get().datos_snapshot["fuentes"]
    arrendador = Persona.objects.get(rut=RUT_ARRENDADOR)
    representacion = RepresentanteLegal.objects.get(persona__rut=RUT_REPRESENTANTE)

    assert fuentes == {
        "tramite": caso.pk,
        "cliente": caso.cliente_id,
        "empresa": caso.cliente.empresa_id,
        "representante_legal": representacion.pk,
        "persona_representante": representacion.persona_id,
        "persona_arrendador": arrendador.pk,
    }


def test_only_the_parties_sign_owner_first(caso):
    firmantes = list(caso.documentos.get().firmantes.order_by("orden"))

    assert [(f.rol, f.persona.rut) for f in firmantes] == [
        ("arrendador", RUT_ARRENDADOR),
        ("cliente_representante", RUT_REPRESENTANTE),
    ]


def test_the_owner_who_is_also_the_representative_signs_in_both_roles(
    django_capture_on_commit_callbacks,
):
    cliente = cliente_empresa()
    base = datos_vehiculo(cliente)
    representante = base["representante"]
    caso = iniciar(
        ejecutar=django_capture_on_commit_callbacks,
        cliente=cliente,
        arrendador={
            "rut": representante["rut"],
            "nombres": representante["nombres"],
            "apellido_paterno": representante["apellido_paterno"],
            "apellido_materno": representante["apellido_materno"],
            "domicilio": representante["domicilio"],
            "comuna": representante["comuna"],
        },
    )

    firmantes = list(caso.documentos.get().firmantes.order_by("orden"))
    assert [f.rol for f in firmantes] == ["arrendador", "cliente_representante"]
    assert firmantes[0].persona_id == firmantes[1].persona_id
    assert Persona.objects.filter(rut=representante["rut"]).count() == 1


def test_an_owner_without_a_domicile_gives_no_document(
    caso,
    django_capture_on_commit_callbacks,
):
    Persona.objects.filter(rut=RUT_ARRENDADOR).update(domicilio="")
    caso.documentos.all().delete()
    Tramite.objects.filter(pk=caso.pk).update(estado="iniciado", motivo=None)

    assert generar(caso) is None

    caso.refresh_from_db()
    assert situacion(caso) == ("pendiente", "falta_informacion")
    assert "domicilio" in caso.detalle_pendiente
    assert not caso.documentos.exists()

    Persona.objects.filter(rut=RUT_ARRENDADOR).update(domicilio="Pasaje Nuevo 1")
    with django_capture_on_commit_callbacks(execute=True):
        reintentar_documento(caso)
    caso.refresh_from_db()
    assert situacion(caso) == ("pendiente", "revision_borrador")


def test_a_role_with_several_signers_keeps_them_all_in_order(caso):
    """An agreement's shareholders share one role (PLT-05)."""
    documento = caso.documentos.get()
    uno, dos = (f.persona for f in documento.firmantes.order_by("orden"))
    tipo = caso.tipo
    tipo.configuracion["firma"]["firmantes"] = ["accionista"]

    class Contexto:
        firmantes = [
            (uno, Firmante.Rol.ACCIONISTA),
            (dos, Firmante.Rol.ACCIONISTA),
            (uno, Firmante.Rol.ARRENDADOR),
        ]

    assert firmantes_en_orden(tipo, Contexto) == [
        (uno, Firmante.Rol.ACCIONISTA),
        (dos, Firmante.Rol.ACCIONISTA),
    ]
