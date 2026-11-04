"""Anonymizing a copy of the database. Every value here is synthetic."""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import pytest
from django.apps import apps
from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError
from django.db import connection
from django.db import models
from django.db import transaction
from django.utils import timezone

from crm_easyoffice.clientes.models import Empresa
from crm_easyoffice.clientes.models import Persona
from crm_easyoffice.clientes.tests.factories import ClienteFactory
from crm_easyoffice.clientes.tests.factories import EmpresaFactory
from crm_easyoffice.clientes.tests.factories import PersonaFactory
from crm_easyoffice.clientes.tests.factories import RepresentanteLegalFactory
from crm_easyoffice.configuracion.models import ConfigEmpresa
from crm_easyoffice.contratos.models import AlertaVencimiento
from crm_easyoffice.contratos.tests.factories import nuevo_contrato
from crm_easyoffice.core.models import RegistroAuditoria
from crm_easyoffice.core.validators import validate_rut
from crm_easyoffice.documentos import formato
from crm_easyoffice.documentos.models import Documento
from crm_easyoffice.documentos.models import SolicitudFirma
from crm_easyoffice.documentos.tests.factories import documento_generado
from crm_easyoffice.inmuebles.models import Autorizante
from crm_easyoffice.inmuebles.models import Oficina
from crm_easyoffice.inmuebles.models import TipoInmueble
from crm_easyoffice.inmuebles.services import CALLE_PENDIENTE
from crm_easyoffice.inmuebles.services import problemas_para_domicilio
from crm_easyoffice.migracion import anonimizacion
from crm_easyoffice.migracion.anonimizacion import ANONIMIZADOS
from crm_easyoffice.migracion.anonimizacion import CONSERVADOS
from crm_easyoffice.migracion.anonimizacion import FUERA_DE_LA_COPIA
from crm_easyoffice.migracion.anonimizacion import REVISADOS
from crm_easyoffice.migracion.anonimizacion import TEXTO_FIJO
from crm_easyoffice.migracion.anonimizacion import TEXTO_PLACEHOLDER
from crm_easyoffice.migracion.anonimizacion import CopiaRechazadaError
from crm_easyoffice.migracion.anonimizacion import anonimizar
from crm_easyoffice.migracion.anonimizacion import plantillas_faltantes
from crm_easyoffice.migracion.anonimizacion import verificar
from crm_easyoffice.tramites.models import EventoTramite
from crm_easyoffice.tramites.models import Tramite
from crm_easyoffice.tramites.tests.factories import preparar_domicilio
from crm_easyoffice.tramites.tests.factories import tramite_con_historia
from crm_easyoffice.users.tests.factories import UserFactory
from crm_easyoffice.ventas.models import EventoPago
from crm_easyoffice.ventas.models import OrdenPago
from crm_easyoffice.ventas.tests.factories import OrdenPagoFactory

pytestmark = pytest.mark.django_db

DIRECCION_ANTIGUA = "Pasaje Antiguo Inventado 99"
HOY = timezone.make_aware(timezone.datetime(2026, 1, 15))


@pytest.fixture
def es_la_copia(monkeypatch) -> None:
    monkeypatch.setattr(
        anonimizacion,
        "NOMBRE_BD_COPIA",
        connection.settings_dict["NAME"],
    )


@pytest.fixture
def caso() -> dict:
    """A company, its representative, a case and a document with a frozen snapshot."""
    preparar_domicilio()
    persona = PersonaFactory.create(
        rut="12345678-5",
        nombres="Sigrid Ventura",
        apellido_paterno="Quispealaya",
        apellido_materno="Zubizarreta",
        domicilio="Avenida Inventada 1234",
        comuna="Comuna Inventada",
        region="Region Inventada",
        email="sigrid.inventada@example.org",
        telefono="+56987654321",
    )
    empresa = EmpresaFactory.create(
        rut="76543210-3",
        razon_social="Comercial Inventada del Norte SpA",
        nombre_fantasia="Inventada Norte",
        giro="Venta de cosas inventadas",
        email="contacto.inventada@example.org",
        telefono="+56912300000",
    )
    representante = RepresentanteLegalFactory.create(
        persona=persona,
        empresa=empresa,
        vigente_desde=date(2026, 1, 1),
        sitio_o_notaria="Notaria Inventada de Arica",
    )
    cliente = ClienteFactory.create(persona=None, empresa=empresa)
    usuario = UserFactory.create(
        email="ejecutivo.inventado@example.org",
        name="Ejecutivo Inventado",
    )
    tramite = tramite_con_historia(
        (HOY, Tramite.Estado.PENDIENTE, "firma"),
        cliente=cliente,
        creado_por=usuario,
        detalle_pendiente="Sigrid Ventura debe corregir su domicilio",
    )
    EventoTramite.objects.filter(tramite=tramite).update(
        detalle="Sigrid Ventura rechazó la firma",
    )
    documento = documento_generado(
        tramite,
        1,
        HOY,
        archivo_firmado="prueba/firmado.pdf",
        sha256_firmado="0" * 64,
    )
    Documento.objects.filter(pk=documento.pk).update(
        datos_snapshot={
            "valores": {
                "folio": "LF-0001-2026",
                "fecha_inicio": "15 DE JULIO DE 2026",
                "servicios": [{"nombre": "DOMICILIO TRIBUTARIO", "precio": "59.990"}],
                "empresa": {
                    "razon_social": empresa.razon_social,
                    "rut": formato.rut(empresa.rut),
                },
                "representante": {
                    "nombre": persona.nombre_completo.upper(),
                    "rut": formato.rut(persona.rut),
                    "domicilio": DIRECCION_ANTIGUA.upper(),
                },
                "aviso": {
                    "mail": "aviso.antiguo@example.org",
                    "celular": "+56955544433",
                },
            },
            "fuentes": {"tramite": tramite.pk},
            "imagenes": {"cedula_anverso": "a" * 64, "cedula_reverso": "b" * 64},
            "plantilla": {"codigo": "PLT-01", "version": 1, "sha256": "c" * 64},
        },
    )
    contrato = nuevo_contrato(cliente=cliente)
    AlertaVencimiento.objects.create(
        contrato=contrato,
        umbral_dias=30,
        fecha_vencimiento=contrato.fecha_vencimiento,
        estado=AlertaVencimiento.Estado.GESTIONADA,
        gestionada_por=usuario,
        gestionada_en=HOY,
        nota="Sigrid Ventura pidió renovar por teléfono",
    )
    return {
        "persona": persona,
        "empresa": empresa,
        "representante": representante,
        "cliente": cliente,
        "usuario": usuario,
        "tramite": tramite,
        "documento": documento,
    }


ORIGINALES = [
    "12345678-5",
    "12.345.678-5",
    "123456785",
    "12345678",
    "76543210-3",
    "76.543.210-3",
    "Sigrid Ventura",
    "SIGRID VENTURA QUISPEALAYA ZUBIZARRETA",
    "Quispealaya",
    "Zubizarreta",
    "Avenida Inventada 1234",
    "Comuna Inventada",
    "Region Inventada",
    "sigrid.inventada@example.org",
    "+56987654321",
    "Comercial Inventada del Norte SpA",
    "Inventada Norte",
    "Venta de cosas inventadas",
    "contacto.inventada@example.org",
    "+56912300000",
    "Notaria Inventada de Arica",
    "ejecutivo.inventado@example.org",
    "Ejecutivo Inventado",
    "Sigrid Ventura debe corregir su domicilio",
    "Sigrid Ventura rechazó la firma",
    "Sigrid Ventura pidió renovar por teléfono",
]


@pytest.mark.usefixtures("es_la_copia")
def test_no_original_value_survives(caso):
    anonimizar()

    assert verificar(set(ORIGINALES)) == []


@pytest.mark.usefixtures("es_la_copia")
def test_a_snapshot_value_no_record_holds_is_replaced_and_searched(caso):
    anonimizar()

    assert verificar({DIRECCION_ANTIGUA, "aviso.antiguo@example.org"}) == []
    documento = Documento.objects.get(pk=caso["documento"].pk)
    valores = documento.datos_snapshot["valores"]
    assert valores["folio"] == "LF-0001-2026"
    assert valores["servicios"][0]["nombre"] == "DOMICILIO TRIBUTARIO"
    assert valores["aviso"]["mail"].endswith("@example.test")


@pytest.mark.usefixtures("es_la_copia")
def test_a_common_name_does_not_match_kept_or_generated_text(caso):
    """Julio is also the month the kept dates print; Calle and Bodega are surnames."""
    PersonaFactory.create(nombres="Julio", apellido_paterno="Calle")
    PersonaFactory.create(nombres="Domicilio", apellido_paterno="Bodega")

    assert anonimizar().personas > 1


@pytest.mark.usefixtures("es_la_copia")
def test_someone_typed_as_test_does_not_match_the_generated_emails(caso):
    PersonaFactory.create(nombres="test", apellido_paterno="example")

    assert anonimizar().personas > 1


@pytest.mark.usefixtures("es_la_copia")
def test_a_table_no_model_knows_is_dropped(caso):
    with connection.cursor() as cursor:
        cursor.execute("CREATE TABLE prospectos_viejos (email text)")
        cursor.execute(
            "INSERT INTO prospectos_viejos VALUES ('prospecto.inventado@example.org')",
        )

    resumen = anonimizar()

    assert resumen.tablas_eliminadas == ["prospectos_viejos"]
    assert "prospectos_viejos" not in connection.introspection.table_names()


def test_verificar_reads_a_table_no_model_knows():
    with connection.cursor() as cursor:
        cursor.execute("CREATE TABLE prospectos_viejos (email text)")
        cursor.execute(
            "INSERT INTO prospectos_viejos VALUES ('prospecto.inventado@example.org')",
        )

    assert verificar({"prospecto.inventado@example.org"}) == ["prospectos_viejos.email"]


@pytest.mark.usefixtures("es_la_copia")
def test_verificar_finds_a_value_in_any_column(caso):
    Tramite.objects.filter(pk=caso["tramite"].pk).update(
        datos={"nota": "sigrid.inventada@example.org"},
    )

    assert verificar({"sigrid.inventada@example.org"}) != []


@pytest.mark.usefixtures("es_la_copia")
def test_a_surviving_value_fails_and_commits_nothing(caso):
    Tramite.objects.filter(pk=caso["tramite"].pk).update(
        datos={"nota": caso["persona"].email},
    )

    with pytest.raises(CopiaRechazadaError, match=r"tramites_tramite\.datos"):
        anonimizar()

    assert Persona.objects.get(pk=caso["persona"].pk).rut == "12345678-5"


@pytest.mark.usefixtures("es_la_copia")
def test_ruts_are_valid_unique_and_the_same_everywhere(caso):
    Empresa.objects.filter(pk=caso["empresa"].pk).update(rut="12345678-5")
    ConfigEmpresa.objects.update(rut="12345678-5")
    Documento.objects.filter(pk=caso["documento"].pk).update(
        datos_snapshot={
            "valores": {"autorizante": {"rut_representante": "12.345.678-5"}},
        },
    )

    anonimizar()

    ruts = list(Persona.objects.values_list("rut", flat=True))
    assert len(ruts) == len(set(ruts))
    for rut in ruts:
        validate_rut(rut)
    assert "12345678-5" not in ruts
    nuevo = Persona.objects.get(pk=caso["persona"].pk).rut
    assert int(nuevo.partition("-")[0]) >= anonimizacion.PRIMER_RUT
    assert Empresa.objects.get(pk=caso["empresa"].pk).rut == nuevo
    assert ConfigEmpresa.objects.get().rut == nuevo
    snapshot = Documento.objects.get(pk=caso["documento"].pk).datos_snapshot
    assert snapshot["valores"]["autorizante"]["rut_representante"] == formato.rut(nuevo)


@pytest.mark.usefixtures("es_la_copia")
def test_private_files_become_placeholders_with_matching_hashes(caso):
    anonimizar()

    documento = Documento.objects.get(pk=caso["documento"].pk)
    for archivo, sha in (
        (documento.archivo_docx, documento.sha256_docx),
        (documento.archivo_pdf, documento.sha256_pdf),
        (documento.archivo_firmado, documento.sha256_firmado),
    ):
        with archivo.open("rb") as abierto:
            assert hashlib.sha256(abierto.read()).hexdigest() == sha
    with documento.archivo_pdf.open("rb") as abierto:
        pdf = abierto.read()
    assert pdf.startswith(b"%PDF-")
    assert TEXTO_PLACEHOLDER.encode() in pdf
    assert documento.archivo_docx.name.endswith(".docx")


@pytest.mark.usefixtures("es_la_copia")
def test_a_branch_stays_ready_for_a_contract(caso):
    anonimizar()

    autorizante = Autorizante.objects.first()
    assert autorizante.documento_identidad.name.endswith(".png")
    with autorizante.documento_identidad.open("rb") as abierto:
        assert abierto.read(8) == b"\x89PNG\r\n\x1a\n"
    assert problemas_para_domicilio(autorizante.inmueble, date(2026, 6, 1)) == []


@pytest.mark.usefixtures("es_la_copia")
def test_a_branch_still_pending_keeps_its_placeholder():
    pendiente = Oficina.objects.filter(calle=CALLE_PENDIENTE).first()
    rol = pendiente.rol_avaluo

    anonimizar()

    pendiente.refresh_from_db()
    assert pendiente.calle == CALLE_PENDIENTE
    assert pendiente.rol_avaluo == rol


@pytest.mark.usefixtures("es_la_copia")
def test_a_warehouse_name_changes(caso):
    bodega = Oficina.objects.create(
        tipo=TipoInmueble.BODEGA,
        rol_avaluo="9999-001",
        nombre="Bodega de Sigrid Quispealaya",
        calle="Camino Inventado",
        numero="7",
        comuna="Quilicura",
        region="Región Metropolitana de Santiago",
    )

    anonimizar()

    bodega.refresh_from_db()
    assert "Sigrid" not in bodega.nombre
    assert bodega.rol_avaluo != "9999-001"


@pytest.mark.usefixtures("es_la_copia")
def test_accounts_and_provider_traces_are_cleared(caso, client):
    client.force_login(caso["usuario"])
    assert Session.objects.exists()
    orden = OrdenPagoFactory.create(estado=OrdenPago.Estado.PENDIENTE)
    EventoPago.objects.create(
        orden=orden,
        proveedor="flow",
        evento="confirmacion",
        clave_dedup="d" * 64,
        payload={"email": "pagador.inventado@example.org"},
        resultado=EventoPago.Resultado.PROCESADO,
    )
    solicitud = SolicitudFirma.objects.create(
        documento=caso["documento"],
        proveedor="http",
        estado=SolicitudFirma.Estado.ENVIADA,
    )

    anonimizar()

    caso["usuario"].refresh_from_db()
    assert not caso["usuario"].has_usable_password()
    assert not Session.objects.exists()
    assert EventoPago.objects.get(orden=orden).payload == {}
    orden.refresh_from_db()
    assert orden.estado == OrdenPago.Estado.CANCELADA
    solicitud.refresh_from_db()
    assert solicitud.estado == SolicitudFirma.Estado.CANCELADA
    assert EventoTramite.objects.filter(detalle=TEXTO_FIJO).exists()


@pytest.mark.usefixtures("es_la_copia")
def test_it_returns_the_identities_for_the_test_psc(caso):
    resumen = anonimizar()

    nueva = Persona.objects.get(pk=caso["persona"].pk)
    assert {
        "rut": nueva.rut,
        "numero_serie": f"A{nueva.rut.partition('-')[0]}",
        "nombre": nueva.nombre_completo,
    } in resumen.identidades


def test_the_command_refuses_without_the_flag():
    with pytest.raises(CommandError, match="--es-copia"):
        call_command("anonimizar_datos")


@pytest.mark.usefixtures("es_la_copia")
@pytest.mark.parametrize(
    "modulo",
    ["config.settings.production", "config.settings.staging"],
)
def test_the_command_refuses_with_production_or_staging_settings(settings, modulo):
    settings.SETTINGS_MODULE = modulo

    with pytest.raises(CommandError, match=modulo):
        call_command("anonimizar_datos", es_copia=True)


def test_the_command_refuses_a_database_that_is_not_the_copy():
    with pytest.raises(CommandError, match="not 'crm_copia'"):
        call_command("anonimizar_datos", es_copia=True)


@pytest.mark.usefixtures("es_la_copia")
def test_the_command_refuses_when_a_template_file_is_missing():
    assert plantillas_faltantes() != []

    with pytest.raises(CommandError, match="Template files missing"):
        call_command("anonimizar_datos", es_copia=True)


def _campos_de_texto(modelo: type[models.Model]) -> set[str]:
    tipos = (models.CharField, models.TextField, models.JSONField, models.FileField)
    return {
        campo.name
        for campo in modelo._meta.local_fields  # noqa: SLF001
        if isinstance(campo, tipos)
    }


def test_every_text_field_of_the_project_is_classified():
    """A new field must be declared personal or not before it can reach staging."""
    sin_clasificar = {}
    for modelo in apps.get_models():
        if not modelo.__module__.startswith("crm_easyoffice."):
            continue
        etiqueta = modelo._meta.label  # noqa: SLF001
        conocidos = (
            ANONIMIZADOS.get(etiqueta, set())
            | CONSERVADOS.get(etiqueta, set())
            | REVISADOS.get(etiqueta, set())
            | FUERA_DE_LA_COPIA.get(etiqueta, set())
        )
        faltan = _campos_de_texto(modelo) - conocidos
        if faltan:
            sin_clasificar[etiqueta] = sorted(faltan)
    assert sin_clasificar == {}


def test_no_field_is_classified_twice_or_invented():
    for etiqueta in set(ANONIMIZADOS) | set(CONSERVADOS) | set(REVISADOS):
        anonimizados = ANONIMIZADOS.get(etiqueta, set())
        conservados = CONSERVADOS.get(etiqueta, set())
        revisados = REVISADOS.get(etiqueta, set())
        assert not (anonimizados & conservados)
        assert not (revisados & (anonimizados | conservados))
        opciones = apps.get_model(etiqueta)._meta  # noqa: SLF001
        existentes = {campo.name for campo in opciones.fields}
        assert (anonimizados | conservados | revisados) <= existentes


@pytest.mark.usefixtures("es_la_copia")
def test_the_audit_log_keeps_its_rows_and_its_protection(caso):
    """Anonymizing neither empties the log nor fails because of what it holds."""
    anonimizar()

    assert RegistroAuditoria.objects.exists()
    with (
        pytest.raises(DatabaseError, match="no se puede modificar"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute("DELETE FROM core_registroauditoria")


def test_the_audit_logs_rows_never_leave_the_copy():
    script = Path(settings.BASE_DIR, "scripts/staging/copy_local_db.sh").read_text()
    empaque = script.partition('"==> Packing it"')[2].partition('"==> Uploading')[0]

    assert "--exclude-table-data=core_registroauditoria" in empaque
