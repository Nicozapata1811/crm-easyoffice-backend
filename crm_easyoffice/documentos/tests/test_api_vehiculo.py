"""The vehicle lease (PLT-03) through the API, end to end. Synthetic data.

An executive starts it; confirming the draft charges the client the list
price plus VAT; the client pays in the portal; only the parties sign. There
is never a Contrato or a folio.
"""

from __future__ import annotations

import importlib
from decimal import Decimal
from http import HTTPStatus

import pytest
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APIClient

from crm_easyoffice.clientes.models import Persona
from crm_easyoffice.clientes.tests.factories import ClienteFactory
from crm_easyoffice.clientes.tests.factories import CuentaClienteFactory
from crm_easyoffice.clientes.tests.factories import PersonaFactory
from crm_easyoffice.contratos.models import Contrato
from crm_easyoffice.documentos.models import Firmante
from crm_easyoffice.documentos.models import SolicitudFirma
from crm_easyoffice.documentos.tests.test_firma_avanzada import proveedor  # noqa: F401
from crm_easyoffice.documentos.tests.test_firma_avanzada import webhook
from crm_easyoffice.integrations.payment.base import PaymentResult
from crm_easyoffice.integrations.payment.base import PaymentStatus
from crm_easyoffice.integrations.signature.base import SignatureEventType
from crm_easyoffice.tramites.models import TipoTramite
from crm_easyoffice.tramites.models import Tramite
from crm_easyoffice.tramites.tests.factories import RUT_ARRENDADOR
from crm_easyoffice.tramites.tests.factories import TIPO_VEHICULO
from crm_easyoffice.tramites.tests.factories import cliente_empresa
from crm_easyoffice.tramites.tests.factories import payload_vehiculo
from crm_easyoffice.users.tests.factories import UserFactory
from crm_easyoffice.ventas.models import OrdenPago
from crm_easyoffice.ventas.models import Venta
from crm_easyoffice.ventas.services import aplicar_resultado

pytestmark = pytest.mark.django_db

roles = importlib.import_module("crm_easyoffice.core.migrations.0002_seed_roles")

TRAMITES = reverse("api:tramite-list")
TIPOS = reverse("api:tramite-tipos")
FORMULARIO = reverse("api:tramite-formulario")
PERSONAS = reverse("api:tramite-personas")
PDF_FIRMADO = b"%PDF-1.7\n% firmado sintetico\n%%EOF\n"

NETO, IVA, TOTAL = "30000", "5700", "35700"


def staff(rol: str | None = roles.EJECUTIVO) -> APIClient:
    user = UserFactory.create()
    if rol:
        user.groups.add(Group.objects.get(name=rol))
    client = APIClient()
    client.force_authenticate(user)
    return client


def portal(cuenta) -> APIClient:
    client = APIClient()
    client.force_authenticate(cuenta.user)
    return client


def accion(tramite_id: int, nombre: str) -> str:
    return reverse(f"api:tramite-{nombre}", kwargs={"pk": tramite_id})


@pytest.fixture
def cliente():
    return cliente_empresa()


@pytest.fixture
def ejecutivo():
    return staff()


def iniciar(client, cliente, capture, **extra):
    with capture(execute=True):
        return client.post(TRAMITES, payload_vehiculo(cliente, **extra), format="json")


def confirmar(client, tramite_id: int, capture):
    with capture(execute=True):
        return client.post(accion(tramite_id, "confirmar"))


def pagar(tramite_id: int, capture) -> None:
    """The provider reports the sale paid, as its webhook would."""
    venta = Tramite.objects.get(pk=tramite_id).venta
    orden = OrdenPago.objects.create(
        venta=venta,
        proveedor="simulated",
        monto=venta.total,
    )
    with capture(execute=True):
        aplicar_resultado(
            orden.pk,
            PaymentResult(
                external_id="",
                reference=str(orden.referencia),
                status=PaymentStatus.PAID,
                amount=venta.total,
            ),
            origen="test",
        )


def documento_de(client, tramite_id: int) -> dict:
    (documento,) = client.get(
        reverse("documentos:tramite-documentos", kwargs={"tramite_id": tramite_id}),
    ).json()
    return documento


def subir_firmado(client, tramite_id: int, documento_id: int):
    return client.post(
        reverse(
            "documentos:tramite-documento-subir-firmado",
            kwargs={"tramite_id": tramite_id, "pk": documento_id},
        ),
        {"archivo": SimpleUploadedFile("firmado.pdf", PDF_FIRMADO)},
        format="multipart",
    )


class TestFormulario:
    def test_the_type_names_its_own_form_and_client_kind(self, ejecutivo):
        tipos = {t["codigo"]: t for t in ejecutivo.get(TIPOS).json()}

        assert tipos[TIPO_VEHICULO] == {
            "codigo": TIPO_VEHICULO,
            "nombre": "Arriendo de vehículo",
            "tipos_cliente": ["empresa"],
            "formulario": "PLT-03",
        }

    def test_it_offers_the_form_with_the_price_split(self, ejecutivo, cliente):
        cuerpo = ejecutivo.get(
            FORMULARIO,
            {"tipo": TIPO_VEHICULO, "cliente": cliente.pk},
        ).json()

        assert (cuerpo["disponible"], cuerpo["problemas"]) == (True, [])
        assert cuerpo["formulario"] == "PLT-03"
        assert cuerpo["precio"] == {
            "servicio": "Arriendo de vehículo",
            "precio_confirmado": False,
            "neto": NETO,
            "iva": IVA,
            "total": TOTAL,
        }
        assert cuerpo["datos"]["empresa"]["rut"] == cliente.empresa.rut
        assert (cuerpo["planes"], cuerpo["inmuebles"], cuerpo["lineas"]) == ([], {}, [])

    def test_a_person_client_is_not_admitted(self, ejecutivo):
        persona = ClienteFactory.create()

        cuerpo = ejecutivo.get(
            FORMULARIO,
            {"tipo": TIPO_VEHICULO, "cliente": persona.pk},
        ).json()

        assert cuerpo["disponible"] is False
        assert cuerpo["problemas"] == [
            "«Arriendo de vehículo» no es para este tipo de cliente.",
        ]

    def test_a_service_without_a_price_stops_the_case(self, ejecutivo, cliente):
        from crm_easyoffice.ventas.models import Servicio  # noqa: PLC0415

        Servicio.objects.filter(codigo="arriendo-vehiculo").update(precio_base=None)

        cuerpo = ejecutivo.get(
            FORMULARIO,
            {"tipo": TIPO_VEHICULO, "cliente": cliente.pk},
        ).json()

        assert cuerpo["disponible"] is False
        assert "no tiene precio" in cuerpo["problemas"][0]

    def test_it_is_not_started_from_the_portal(self):
        cuenta = CuentaClienteFactory.create(cliente=cliente_empresa())

        tipos = portal(cuenta).get(TIPOS, {"canal": "portal"})

        assert tipos.status_code == HTTPStatus.FORBIDDEN


class TestPersonas:
    def test_a_person_on_record_fills_the_block(self, ejecutivo):
        persona = PersonaFactory.create(domicilio="Calle de Ejemplo 1", comuna="Ñuñoa")

        respuesta = ejecutivo.get(PERSONAS, {"rut": persona.rut})

        assert respuesta.status_code == HTTPStatus.OK
        assert respuesta.json()["nombres"] == persona.nombres
        assert respuesta.json()["domicilio"] == "Calle de Ejemplo 1"

    def test_an_unknown_rut_is_not_found_and_a_bad_one_is_refused(self, ejecutivo):
        assert (
            ejecutivo.get(PERSONAS, {"rut": RUT_ARRENDADOR}).status_code
            == HTTPStatus.NOT_FOUND
        )
        assert (
            ejecutivo.get(PERSONAS, {"rut": "12345678-9"}).status_code
            == HTTPStatus.BAD_REQUEST
        )

    def test_it_needs_the_permission_to_start_cases(self):
        assert staff(None).get(PERSONAS, {"rut": RUT_ARRENDADOR}).status_code == (
            HTTPStatus.FORBIDDEN
        )


class TestValidacion:
    @pytest.mark.parametrize(
        ("cambio", "campo"),
        [
            ({"vehiculo": {"patente": "123ABC"}}, ("vehiculo", "patente")),
            ({"vehiculo": {"anio": 1800}}, ("vehiculo", "anio")),
            ({"vehiculo": {"vin": "!!"}}, ("vehiculo", "vin")),
            ({"arrendador": {"rut": "32333444-0"}}, ("arrendador", "rut")),
            ({"fecha": "2999-01-01"}, ("fecha",)),
            ({"fecha_inicio": "no-es-fecha"}, ("fecha_inicio",)),
            ({"plazo_meses": 0}, ("plazo_meses",)),
            ({"renta": 0}, ("renta",)),
            ({"dia_pago": 31}, ("dia_pago",)),
            ({"medio_pago": "otro"}, ("medio_pago_otro",)),
        ],
    )
    def test_a_bad_value_is_a_field_error_and_starts_nothing(
        self,
        cambio,
        campo,
        ejecutivo,
        cliente,
        django_capture_on_commit_callbacks,
    ):
        payload = payload_vehiculo(cliente)
        for clave, valor in cambio.items():
            payload[clave] = (
                {**payload[clave], **valor} if isinstance(valor, dict) else valor
            )
        with django_capture_on_commit_callbacks(execute=True):
            respuesta = ejecutivo.post(TRAMITES, payload, format="json")

        assert respuesta.status_code == HTTPStatus.BAD_REQUEST
        error = respuesta.json()
        for clave in campo:
            error = error[clave]
        assert error
        assert not Tramite.objects.exists()

    def test_a_plate_is_stored_in_capitals_without_separators(
        self,
        ejecutivo,
        cliente,
        django_capture_on_commit_callbacks,
    ):
        payload = payload_vehiculo(cliente)
        payload["vehiculo"]["patente"] = "bb-df 12"

        creado = iniciar(
            ejecutivo,
            cliente,
            django_capture_on_commit_callbacks,
            vehiculo=payload["vehiculo"],
        )

        assert creado.json()["datos"]["vehiculo"]["patente"] == "BBDF12"

    def test_a_person_of_someone_else_is_reused_but_never_overwritten(
        self,
        ejecutivo,
        cliente,
        django_capture_on_commit_callbacks,
    ):
        ajena = PersonaFactory.create(
            rut=RUT_ARRENDADOR,
            nombres="Rodrigo Ignacio",
            apellido_paterno="Inventado",
            apellido_materno="Ficticio",
            domicilio="Otra Calle 1",
            comuna="",
            email="",
        )
        ClienteFactory.create(persona=ajena)

        rechazado = iniciar(ejecutivo, cliente, django_capture_on_commit_callbacks)

        assert rechazado.status_code == HTTPStatus.BAD_REQUEST
        assert list(rechazado.json()["arrendador"]) == ["domicilio"]
        assert not Tramite.objects.exists()

        payload = payload_vehiculo(cliente)
        payload["arrendador"]["domicilio"] = "otra calle 1"
        creado = iniciar(
            ejecutivo,
            cliente,
            django_capture_on_commit_callbacks,
            arrendador=payload["arrendador"],
        )

        assert creado.status_code == HTTPStatus.CREATED, creado.json()
        ajena.refresh_from_db()
        # Kept as on record; only what was empty and the lease needs is filled.
        assert ajena.domicilio == "Otra Calle 1"
        assert ajena.comuna == "La Florida"


def test_the_case_runs_from_start_to_completed_with_the_assisted_upload(
    ejecutivo,
    cliente,
    django_capture_on_commit_callbacks,
):
    cuenta = CuentaClienteFactory.create(cliente=cliente)
    capture = django_capture_on_commit_callbacks

    creado = iniciar(ejecutivo, cliente, capture)
    assert creado.status_code == HTTPStatus.CREATED, creado.json()
    cuerpo = creado.json()
    tramite_id = cuerpo["id"]
    assert (cuerpo["tipo_codigo"], cuerpo["canal"]) == (TIPO_VEHICULO, "backoffice")
    assert (cuerpo["contrato"], cuerpo["venta"]) == (None, None)
    assert cuerpo["cliente"]["tiene_cuenta_portal"] is True
    assert {"etiqueta": "Patente", "valor": "BBDF12"} in cuerpo["resumen"]
    assert {"etiqueta": "Vigencia", "valor": "02-10-2026 al 01-10-2027"} in (
        cuerpo["resumen"]
    )
    assert cuerpo["formulario"]["arrendador"]["rut"] == RUT_ARRENDADOR

    detalle = ejecutivo.get(accion(tramite_id, "detail")).json()
    assert detalle["motivo"]["codigo"] == "revision_borrador"
    documento = documento_de(ejecutivo, tramite_id)
    assert documento["plantilla"].startswith("PLT-03")
    assert [f["rol"] for f in documento["firmantes"]] == [
        "arrendador",
        "cliente_representante",
    ]

    # The client follows it read-only until there is something to pay.
    del_cliente = portal(cuenta)
    visto = del_cliente.get(reverse("portal:tramite-detail", args=[tramite_id])).json()
    assert (visto["accion_cliente"], visto["editable"]) == (None, False)
    assert (
        del_cliente.post(
            reverse("portal:tramite-confirmar", args=[tramite_id]),
        ).status_code
        == HTTPStatus.CONFLICT
    )

    confirmado = confirmar(ejecutivo, tramite_id, capture).json()
    assert confirmado["motivo"]["codigo"] == "pago"
    venta = confirmado["venta"]
    assert (venta["neto"], venta["iva"], venta["total"]) == (NETO, IVA, TOTAL)
    assert [
        (i["servicio"], i["neto"], i["iva"], i["subtotal"]) for i in venta["items"]
    ] == [
        ("arriendo-vehiculo", NETO, IVA, TOTAL),
    ]
    assert Venta.objects.count() == 1
    assert not Contrato.objects.exists()

    # The same three amounts in the client's portal, where the sale is paid.
    visto = del_cliente.get(reverse("portal:tramite-detail", args=[tramite_id])).json()
    assert visto["accion_cliente"] == "pagar"
    en_portal = del_cliente.get(
        reverse("portal:venta-detail", args=[venta["id"]]),
    ).json()
    assert (en_portal["neto"], en_portal["iva"], en_portal["total"]) == (
        NETO,
        IVA,
        TOTAL,
    )
    with capture(execute=True):
        orden = del_cliente.post(
            reverse("portal:venta-pagar", args=[venta["id"]]),
            {"proveedor": "simulated"},
            format="json",
        )
    assert orden.status_code == HTTPStatus.ACCEPTED, orden.json()
    assert orden.json()["monto"] == TOTAL

    pagar(tramite_id, capture)
    detalle = ejecutivo.get(accion(tramite_id, "detail")).json()
    assert detalle["motivo"]["codigo"] == "firma"
    assert detalle["editable"] is False

    subido = subir_firmado(ejecutivo, tramite_id, documento["id"])
    assert subido.status_code == HTTPStatus.OK, subido.json()
    tramite = Tramite.objects.get(pk=tramite_id)
    assert tramite.estado == "completado"
    assert tramite.contrato is None
    assert not Contrato.objects.exists()
    assert Venta.objects.get().total == Decimal(TOTAL)


def test_a_client_without_a_portal_account_stays_waiting_for_payment(
    ejecutivo,
    cliente,
    django_capture_on_commit_callbacks,
):
    tramite_id = iniciar(ejecutivo, cliente, django_capture_on_commit_callbacks).json()[
        "id"
    ]

    confirmado = confirmar(ejecutivo, tramite_id, django_capture_on_commit_callbacks)

    cuerpo = confirmado.json()
    assert cuerpo["motivo"]["codigo"] == "pago"
    assert cuerpo["cliente"]["tiene_cuenta_portal"] is False
    assert cuerpo["venta"]["estado"] == "pendiente_pago"
    # Nothing marks it paid by hand: the document cannot be signed yet.
    documento = documento_de(ejecutivo, tramite_id)
    assert subir_firmado(ejecutivo, tramite_id, documento["id"]).status_code == (
        HTTPStatus.CONFLICT
    )


def test_editing_the_draft_cancels_its_sale_and_redoes_the_document(
    ejecutivo,
    cliente,
    django_capture_on_commit_callbacks,
):
    capture = django_capture_on_commit_callbacks
    tramite_id = iniciar(ejecutivo, cliente, capture).json()["id"]
    confirmar(ejecutivo, tramite_id, capture)
    cambios = payload_vehiculo(cliente, renta=300000, plazo_meses=6)
    del cambios["tipo"], cambios["cliente"]

    with capture(execute=True):
        editado = ejecutivo.put(accion(tramite_id, "detail"), cambios, format="json")

    assert editado.status_code == HTTPStatus.OK, editado.json()
    cuerpo = ejecutivo.get(accion(tramite_id, "detail")).json()
    assert cuerpo["motivo"]["codigo"] == "revision_borrador"
    assert (cuerpo["venta"], cuerpo["datos"]["renta"]) == (None, 300000)
    assert Venta.objects.get().estado == Venta.Estado.ANULADA
    assert Tramite.objects.get(pk=tramite_id).documentos.count() == 2  # noqa: PLR2004
    assert Persona.objects.filter(rut=RUT_ARRENDADOR).count() == 1

    confirmar(ejecutivo, tramite_id, capture)
    assert Venta.objects.filter(estado=Venta.Estado.PENDIENTE_PAGO).count() == 1


def test_the_owner_typed_wrong_can_be_corrected_on_the_same_case(
    ejecutivo,
    cliente,
    django_capture_on_commit_callbacks,
):
    capture = django_capture_on_commit_callbacks
    tramite_id = iniciar(ejecutivo, cliente, capture).json()["id"]
    cambios = payload_vehiculo(cliente)
    del cambios["tipo"], cambios["cliente"]
    cambios["arrendador"]["domicilio"] = "Avenida Corregida 1"

    with capture(execute=True):
        editado = ejecutivo.put(accion(tramite_id, "detail"), cambios, format="json")

    assert editado.status_code == HTTPStatus.OK, editado.json()
    assert Persona.objects.get(rut=RUT_ARRENDADOR).domicilio == "Avenida Corregida 1"


def test_the_advanced_signature_sends_only_the_parties_and_completes(
    ejecutivo,
    cliente,
    proveedor,  # noqa: F811 - fixture
    django_capture_on_commit_callbacks,
):
    capture = django_capture_on_commit_callbacks
    tipo = TipoTramite.objects.get(codigo=TIPO_VEHICULO)
    tipo.configuracion["firma"]["nivel"] = "avanzada"
    tipo.save()
    CuentaClienteFactory.create(cliente=cliente)
    tramite_id = iniciar(ejecutivo, cliente, capture).json()["id"]
    confirmar(ejecutivo, tramite_id, capture)

    pagar(tramite_id, capture)

    solicitud = SolicitudFirma.objects.get()
    assert solicitud.estado == SolicitudFirma.Estado.ENVIADA
    firmantes = list(solicitud.documento.firmantes.order_by("orden"))
    assert [f.rol for f in firmantes] == ["arrendador", "cliente_representante"]
    assert all(f.id_externo for f in firmantes)
    documento = documento_de(ejecutivo, tramite_id)
    assert subir_firmado(ejecutivo, tramite_id, documento["id"]).status_code == (
        HTTPStatus.CONFLICT
    )

    publico = APIClient()
    proveedor.sign_next(solicitud.id_externo)
    webhook(publico, proveedor, solicitud, SignatureEventType.SIGNER_SIGNED, capture)
    proveedor.sign_next(solicitud.id_externo)
    webhook(publico, proveedor, solicitud, SignatureEventType.COMPLETED, capture)

    tramite = Tramite.objects.get(pk=tramite_id)
    assert tramite.estado == "completado"
    assert all(
        f.estado == Firmante.Estado.FIRMADO for f in solicitud.documento.firmantes.all()
    )
    assert not Contrato.objects.exists()


def test_the_demo_switch_to_the_advanced_signature_keeps_the_parties_as_signers():
    from django.core.management import call_command  # noqa: PLC0415

    call_command("seed_demo_firma_avanzada", force=True)

    firma = TipoTramite.objects.get(codigo=TIPO_VEHICULO).configuracion["firma"]
    assert firma == {
        "nivel": "avanzada",
        "firmantes": ["arrendador", "cliente_representante"],
    }
