"""The signing flow through the services: identity, codes, order, decline,
cancellation and expiry."""

from datetime import timedelta

import pytest
from django.utils import timezone

from psc import firma
from psc import pki
from psc import servicios
from psc.models import Certificado
from psc.models import EntregaWebhook
from psc.models import Firmante
from psc.models import Solicitud

from .conftest import PERSONAS
from .conftest import firmantes
from .conftest import firmar_todo
from .conftest import ultimo_codigo

pytestmark = pytest.mark.django_db


def _primero(solicitud) -> Firmante:
    return solicitud.firmantes.get(orden=1)


def _verificar(firmante: Firmante) -> None:
    serie = PERSONAS[firmante.orden - 1][2]
    assert servicios.verificar_identidad(
        firmante,
        {"rut": firmante.rut, "numero_serie": serie},
    )


def test_creation_invites_only_the_first_signer(solicitud, mailoutbox):
    assert [m.to for m in mailoutbox] == [["uno@example.test"]]
    assert "/firmar/" in mailoutbox[0].body
    assert bytes(solicitud.documento_actual).startswith(
        bytes(solicitud.documento_original),
    )


@pytest.mark.parametrize(
    "datos",
    [
        {"rut": "90000301-3", "numero_serie": "OTRA"},
        {"rut": "90000302-1", "numero_serie": "A90000302"},
        {"rut": "", "numero_serie": ""},
    ],
)
def test_identity_check_failures(solicitud, datos):
    firmante = _primero(solicitud)
    assert not servicios.verificar_identidad(firmante, datos)
    firmante.refresh_from_db()
    assert firmante.intentos_identidad == 1
    assert not Certificado.objects.filter(firmante=firmante).exists()


def test_identity_attempts_are_limited(solicitud, settings):
    firmante = _primero(solicitud)
    for _ in range(settings.IDENTIDAD_INTENTOS):
        servicios.verificar_identidad(
            firmante,
            {"rut": firmante.rut, "numero_serie": "mal"},
        )
    with pytest.raises(servicios.OperacionNoPermitidaError, match="intentos"):
        servicios.verificar_identidad(
            firmante,
            {"rut": firmante.rut, "numero_serie": "A90000301"},
        )

    servicios.reenviar(firmante)
    _verificar(firmante)


def test_identity_accepts_formatted_input(solicitud):
    firmante = _primero(solicitud)
    assert servicios.verificar_identidad(
        firmante,
        {"rut": "90.000.301-3", "numero_serie": "a90000301"},
    )


def test_identity_issues_a_single_use_certificate_with_an_encrypted_key(solicitud):
    firmante = _primero(solicitud)
    _verificar(firmante)
    certificado = Certificado.objects.get(firmante=firmante)
    assert b"ENCRYPTED PRIVATE KEY" in bytes(certificado.clave_cifrada)
    assert "Persona Ficticia Uno" in certificado.pem or certificado.pem.startswith(
        "-----BEGIN CERTIFICATE",
    )


def test_a_code_is_needed_and_the_key_is_gone_after_signing(solicitud, mailoutbox):
    firmante = _primero(solicitud)
    _verificar(firmante)
    with pytest.raises(servicios.OperacionNoPermitidaError, match="venció"):
        servicios.firmar(firmante, "000000", consiente=True)

    servicios.enviar_codigo(firmante)
    servicios.firmar(firmante, ultimo_codigo(mailoutbox), consiente=True)

    firmante.refresh_from_db()
    assert firmante.estado == Firmante.Estado.FIRMADO
    assert firmante.codigo_verificacion.startswith("PRU-")
    assert Certificado.objects.get(firmante=firmante).clave_cifrada is None


def test_codes_expire(solicitud, mailoutbox):
    firmante = _primero(solicitud)
    _verificar(firmante)
    servicios.enviar_codigo(firmante)
    firmante.codigos.update(expira_en=timezone.now() - timedelta(seconds=1))

    with pytest.raises(servicios.OperacionNoPermitidaError, match="venció"):
        servicios.firmar(firmante, ultimo_codigo(mailoutbox), consiente=True)


def test_code_attempts_are_limited(solicitud, mailoutbox, settings):
    firmante = _primero(solicitud)
    _verificar(firmante)
    servicios.enviar_codigo(firmante)
    codigo = ultimo_codigo(mailoutbox)
    incorrecto = "111111" if codigo != "111111" else "222222"
    for _ in range(settings.OTP_INTENTOS):
        with pytest.raises(servicios.OperacionNoPermitidaError, match="incorrecto"):
            servicios.firmar(firmante, incorrecto, consiente=True)

    with pytest.raises(servicios.OperacionNoPermitidaError, match="intentos"):
        servicios.firmar(firmante, codigo, consiente=True)


def test_a_new_code_replaces_the_previous_one(solicitud, mailoutbox):
    firmante = _primero(solicitud)
    _verificar(firmante)
    servicios.enviar_codigo(firmante)
    viejo = ultimo_codigo(mailoutbox)
    servicios.enviar_codigo(firmante)
    nuevo = ultimo_codigo(mailoutbox)
    if viejo != nuevo:
        with pytest.raises(servicios.OperacionNoPermitidaError):
            servicios.firmar(firmante, viejo, consiente=True)
    servicios.firmar(firmante, nuevo, consiente=True)


def test_consent_is_required(solicitud, mailoutbox):
    firmante = _primero(solicitud)
    _verificar(firmante)
    servicios.enviar_codigo(firmante)
    with pytest.raises(servicios.OperacionNoPermitidaError, match="aceptar"):
        servicios.firmar(firmante, ultimo_codigo(mailoutbox), consiente=False)


def test_signers_sign_in_order(solicitud, mailoutbox):
    segundo = solicitud.firmantes.get(orden=2)
    with pytest.raises(servicios.OperacionNoPermitidaError, match="turno"):
        servicios.verificar_identidad(
            segundo,
            {"rut": segundo.rut, "numero_serie": "A90000302"},
        )

    firmar_todo(solicitud, mailoutbox, hasta=1)

    assert mailoutbox[-1].to == ["dos@example.test"]
    _verificar(segundo)


def test_all_signers_complete_the_request_with_a_valid_pdf(solicitud, mailoutbox):
    solicitud = firmar_todo(solicitud, mailoutbox)

    assert solicitud.estado == Solicitud.Estado.COMPLETADA
    firmado = bytes(solicitud.documento_actual)
    assert firmado.startswith(bytes(solicitud.documento_original))
    informe = firma.validar(firmado, pki.cargar())
    assert informe.valido, informe.errores
    assert [f.rut for f in informe.firmas] == ["90000301-3", "90000302-1", "90000303-K"]
    assert informe.sello_documento
    tipos = list(
        EntregaWebhook.objects.filter(solicitud=solicitud).values_list(
            "tipo",
            flat=True,
        ),
    )
    assert tipos == [
        "firmante.firmo",
        "firmante.firmo",
        "firmante.firmo",
        "solicitud.completada",
    ]


def test_declining_closes_the_request_and_revokes_unused_certificates(solicitud):
    firmante = _primero(solicitud)
    _verificar(firmante)

    servicios.rechazar(firmante, "Los datos de la empresa están mal.")

    solicitud.refresh_from_db()
    assert solicitud.estado == Solicitud.Estado.RECHAZADA
    firmante.refresh_from_db()
    assert firmante.motivo_rechazo == "Los datos de la empresa están mal."
    certificado = Certificado.objects.get(firmante=firmante)
    assert certificado.revocado_en is not None
    assert certificado.clave_cifrada is None
    assert (
        int(certificado.numero_serie),
        certificado.revocado_en,
    ) in servicios.revocados()
    assert EntregaWebhook.objects.get(solicitud=solicitud).tipo == "firmante.rechazo"


def test_declining_needs_a_reason(solicitud):
    with pytest.raises(servicios.OperacionNoPermitidaError, match="motivo"):
        servicios.rechazar(_primero(solicitud), "  ")


def test_cancelled_requests_cannot_be_signed(solicitud):
    servicios.cancelar(solicitud)
    with pytest.raises(servicios.OperacionNoPermitidaError, match="cancelada"):
        _verificar(_primero(solicitud))


def test_overdue_requests_expire_and_notify(solicitud):
    Solicitud.objects.filter(pk=solicitud.pk).update(
        expira_en=timezone.now() - timedelta(minutes=1),
    )

    assert servicios.expirar_vencidas() == 1
    assert servicios.expirar_vencidas() == 0

    solicitud.refresh_from_db()
    assert solicitud.estado == Solicitud.Estado.EXPIRADA
    assert EntregaWebhook.objects.get(solicitud=solicitud).tipo == "solicitud.expirada"


def test_creation_rejects_bad_input(cliente_api, pdf):
    with pytest.raises(servicios.DatosInvalidosError) as error:
        servicios.crear_solicitud(
            cliente_api,
            b"no",
            nombre_documento="x",
            firmantes=[],
        )
    assert set(error.value.errores) == {"documento", "firmantes"}

    desordenados = firmantes(2)
    desordenados[1] = servicios.FirmanteNuevo(
        **{**desordenados[1].__dict__, "orden": 5},
    )
    with pytest.raises(servicios.DatosInvalidosError, match="orden"):
        servicios.crear_solicitud(
            cliente_api,
            pdf,
            nombre_documento="x",
            firmantes=desordenados,
        )
