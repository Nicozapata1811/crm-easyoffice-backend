"""End to end: a warehouse case signed by three people through the test PSC.

Runs against the live compose stack, not a test database: the CRM, its
Celery worker, Gotenberg, the test PSC with its worker, and Mailpit. The
case is filed with the CRM's own services, the signers sign on the PSC's
pages with the codes Mailpit receives, the PSC's webhooks complete the case,
and the PSC validates the final PDF against its test root.

    just e2e-firma

Every person and company is fictitious; the signatures have no legal validity.
"""

from __future__ import annotations

import html
import os
import re
import time
from datetime import date
from typing import Any

import django
import httpx
import pytest

pytestmark = pytest.mark.e2e

PSC = os.environ.get("E2E_PSC_URL", "http://firma-sandbox:8100")
MAILPIT = os.environ.get("E2E_MAILPIT_URL", "http://mailpit:8025")
ESPERA = float(os.environ.get("E2E_ESPERA_SEGUNDOS", "180"))

# The fictitious registry of the test PSC (firma_sandbox/fixtures).
REPRESENTANTE = {"rut": "90000301-3", "serie": "A90000301"}
SERIES = {
    "90000001-4": "A90000001",
    "90000201-7": "A90000201",
    "90000202-5": "A90000202",
    REPRESENTANTE["rut"]: REPRESENTANTE["serie"],
}
EMPRESA_DEMO = "76900301-0"


def esperar(condicion, descripcion: str):
    limite = time.monotonic() + ESPERA
    while time.monotonic() < limite:
        if resultado := condicion():
            return resultado
        time.sleep(2)
    pytest.fail(f"Timed out waiting for {descripcion}.")


@pytest.fixture(scope="module")
def crm():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
    django.setup()
    from crm_easyoffice.tramites import services  # noqa: PLC0415

    return services


def _cliente_demo():
    from crm_easyoffice.clientes.models import Cliente  # noqa: PLC0415
    from crm_easyoffice.clientes.models import Empresa  # noqa: PLC0415

    empresa, _ = Empresa.objects.get_or_create(
        rut=EMPRESA_DEMO,
        defaults={
            "razon_social": "Comercial Demo de Firma SpA",
            "email": "demo-firma@example.test",
        },
    )
    cliente, _ = Cliente.objects.get_or_create(empresa=empresa)
    return cliente


def _datos(cliente, sucursal, bodega, correo: str) -> dict[str, Any]:
    return {
        "empresa": {
            "rut": cliente.empresa.rut,
            "razon_social": "Comercial Demo de Firma SpA",
            "giro": "Actividad de ejemplo",
        },
        "representante": {
            "rut": REPRESENTANTE["rut"],
            "nombres": "Representante",
            "apellido_paterno": "Demo",
            "apellido_materno": "Uno",
            "domicilio": "Calle Ficticia 1",
            "comuna": "Santiago",
            "region": "Región Metropolitana de Santiago",
        },
        "personeria": {
            "fecha_instrumento": date(2026, 1, 2),
            "sitio_o_notaria": "Notaría de Ejemplo",
        },
        "email_aviso": correo,
        "movil_aviso": "912345678",
        "plan": "anual",
        "sucursal": sucursal.pk,
        "bodega": bodega.pk,
        "fecha_inicio": date.today(),  # noqa: DTZ011 - the local date, as the form sends it
    }


def _correos(destino: str) -> list[dict]:
    respuesta = httpx.get(
        f"{MAILPIT}/api/v1/search",
        params={"query": f'to:"{destino}"'},
    )
    respuesta.raise_for_status()
    return respuesta.json()["messages"]


def _texto(mensaje: dict) -> str:
    return httpx.get(f"{MAILPIT}/api/v1/message/{mensaje['ID']}").json()["Text"]


def _invitacion(destino: str, folio: str) -> str:
    def buscar() -> str | None:
        for mensaje in _correos(destino):
            if folio in mensaje["Subject"]:
                enlace = re.search(r"https?://\S+/firmar/\S+/", _texto(mensaje))
                if enlace:
                    return re.sub(r"^https?://[^/]+", PSC, enlace.group(0))
        return None

    return esperar(buscar, f"the signing link for {destino}")


def _codigo(destino: str, despues_de: set[str]) -> str:
    def buscar() -> str | None:
        for mensaje in _correos(destino):
            if "código" in mensaje["Subject"] and mensaje["ID"] not in despues_de:
                return mensaje["Subject"].rsplit(" ", 1)[-1]
        return None

    return esperar(buscar, f"the one-time code for {destino}")


def _csrf(pagina: str) -> str:
    return html.unescape(
        re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', pagina).group(1),
    )


def _firmar(enlace: str, destino: str, rut: str) -> None:
    with httpx.Client(follow_redirects=True, timeout=60) as navegador:
        pagina = navegador.get(enlace).text
        assert "Verifica tu identidad" in pagina
        pagina = navegador.post(
            enlace,
            data={
                "csrfmiddlewaretoken": _csrf(pagina),
                "accion": "identidad",
                "rut": rut,
                "numero_serie": SERIES[rut],
            },
        ).text
        assert "Identidad verificada" in pagina, pagina
        vistos = {m["ID"] for m in _correos(destino)}
        pagina = navegador.post(
            enlace,
            data={"csrfmiddlewaretoken": _csrf(pagina), "accion": "codigo"},
        ).text
        pagina = navegador.post(
            enlace,
            data={
                "csrfmiddlewaretoken": _csrf(pagina),
                "accion": "firmar",
                "codigo": _codigo(destino, vistos),
                "consiento": "si",
            },
        ).text
        assert "Documento firmado" in pagina, pagina


def test_three_signers_sign_and_the_contract_enters_into_force(crm):
    from crm_easyoffice.contratos.models import Contrato  # noqa: PLC0415
    from crm_easyoffice.documentos.models import SolicitudFirma  # noqa: PLC0415
    from crm_easyoffice.inmuebles.models import Oficina  # noqa: PLC0415
    from crm_easyoffice.tramites.models import Tramite  # noqa: PLC0415

    tipo = crm.tipo_tramite("bodega")
    assert crm.nivel_firma(tipo) == crm.AVANZADA, "run seed_demo_firma_avanzada first"
    cliente = _cliente_demo()
    sucursal = Oficina.objects.filter(codigo_sucursal="LF").first()
    bodega = Oficina.objects.get(rol_avaluo="9001-001")
    correo = f"e2e-{int(time.time())}@example.test"

    tramite = crm.iniciar_tramite(
        tipo,
        cliente,
        _datos(cliente, sucursal, bodega, correo),
        canal=Tramite.Canal.BACKOFFICE,
    )
    esperar(
        lambda: (
            crm.situacion(Tramite.objects.get(pk=tramite.pk))
            == (crm.PENDIENTE, crm.REVISION_BORRADOR)
        ),
        "the document (Celery and Gotenberg)",
    )
    crm.confirmar_borrador(tramite, canal=Tramite.Canal.BACKOFFICE)
    solicitud = esperar(
        lambda: SolicitudFirma.objects.filter(
            documento__tramite=tramite,
            estado=SolicitudFirma.Estado.ENVIADA,
        ).first(),
        "the request at the test PSC",
    )
    assert solicitud.ambiente_pruebas
    folio = Tramite.objects.get(pk=tramite.pk).contrato.folio

    firmantes = list(
        solicitud.documento.firmantes.select_related("persona").order_by("orden"),
    )
    assert [f.rol for f in firmantes] == [
        "cliente_representante",
        "representante_emisor",
        "autorizante",
    ]
    for firmante in firmantes:
        destino = firmante.persona.email or correo
        _firmar(_invitacion(destino, folio), destino, firmante.persona.rut)

    completado = esperar(
        lambda: Tramite.objects.filter(pk=tramite.pk, estado=crm.COMPLETADO).first(),
        "the webhooks to complete the case",
    )
    assert completado.contrato.estado == Contrato.Estado.VIGENTE
    documento = solicitud.documento
    documento.refresh_from_db()
    assert all(f.firmado_en for f in documento.firmantes.all())

    with documento.archivo_firmado.open("rb") as archivo:
        firmado = archivo.read()
    informe = httpx.post(
        f"{PSC}/api/v1/validaciones",
        headers={"Authorization": f"Bearer {os.environ['SIGNATURE_API_KEY']}"},
        files={"documento": ("firmado.pdf", firmado, "application/pdf")},
        timeout=60,
    ).json()
    assert informe["valido"], informe
    assert informe["sello_documento"]
    assert [f["rut"] for f in informe["firmas"]] == [f.persona.rut for f in firmantes]
    assert all(f["confiable"] and f["sello_de_tiempo"] for f in informe["firmas"])
