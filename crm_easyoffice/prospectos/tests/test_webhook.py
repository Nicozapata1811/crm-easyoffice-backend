"""Tests for the website webhook. All data here is synthetic."""

from http import HTTPStatus
from urllib.parse import urlencode

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APIClient

from crm_easyoffice.prospectos.models import Prospecto

TOKEN = "test-webhook-token"  # noqa: S105
WRONG_TOKEN = "wrong-token"  # noqa: S105

VALIDO = {
    "nombre": "Ana Prueba Soto",
    "email": "ana.prueba@example.com",
    "telefono": "+56 9 1234 5678",
    "servicio": "domicilio-tributario",
    "plan": "anual",
    "origen": "sitio-popup",
    "mensaje": "Quiero información del plan anual.",
}

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _webhook_settings(settings):
    settings.WEBHOOK_SITIO_TOKEN = TOKEN
    settings.WEBHOOK_SITIO_THROTTLE_RATE = "100/min"
    cache.clear()


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


def webhook_url(**params) -> str:
    query = {"token": TOKEN, **params}
    return f"{reverse('api:webhook-sitio-prospectos')}?{urlencode(query)}"


def post_form(client: APIClient, data: dict, url: str | None = None):
    return client.post(
        url or webhook_url(),
        urlencode(data),
        content_type="application/x-www-form-urlencoded",
    )


class TestContentTypes:
    def test_form_urlencoded_creates_prospecto(self, api_client):
        response = post_form(api_client, VALIDO)

        assert response.status_code == HTTPStatus.CREATED
        assert response.json() == {"resultado": "creado"}
        prospecto = Prospecto.objects.get()
        assert prospecto.nombre == "Ana Prueba Soto"
        assert prospecto.email == "ana.prueba@example.com"
        assert prospecto.servicio_interes == "domicilio-tributario"
        assert prospecto.plan == "anual"
        assert prospecto.origen == "sitio-popup"
        assert prospecto.formato == "generico"
        assert prospecto.estado == Prospecto.Estado.NUEVO
        assert not prospecto.servicio_desconocido
        assert not prospecto.plan_desconocido

    def test_multipart_creates_prospecto_and_ignores_files(self, api_client):
        data = {**VALIDO, "adjunto": SimpleUploadedFile("cv.txt", b"contenido")}

        response = api_client.post(webhook_url(), data, format="multipart")

        assert response.status_code == HTTPStatus.CREATED
        prospecto = Prospecto.objects.get()
        assert prospecto.nombre == "Ana Prueba Soto"
        assert "adjunto" not in prospecto.payload_original

    def test_json_creates_prospecto(self, api_client):
        response = api_client.post(webhook_url(), VALIDO, format="json")

        assert response.status_code == HTTPStatus.CREATED
        assert Prospecto.objects.get().plan == "anual"

    def test_other_content_types_are_rejected(self, api_client):
        response = api_client.post(
            webhook_url(),
            "nombre=Ana",
            content_type="text/plain",
        )

        assert response.status_code == HTTPStatus.UNSUPPORTED_MEDIA_TYPE
        assert not Prospecto.objects.exists()


class TestToken:
    @pytest.mark.parametrize(
        "url",
        [
            pytest.param(lambda: reverse("api:webhook-sitio-prospectos"), id="missing"),
            pytest.param(lambda: webhook_url(token=WRONG_TOKEN), id="wrong"),
            pytest.param(lambda: webhook_url(token=""), id="empty"),
        ],
    )
    def test_invalid_token_is_forbidden(self, api_client, url):
        response = post_form(api_client, VALIDO, url=url())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert not Prospecto.objects.exists()

    def test_unconfigured_token_rejects_everything(self, api_client, settings):
        settings.WEBHOOK_SITIO_TOKEN = ""

        response = post_form(api_client, VALIDO, url=webhook_url(token=""))

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert not Prospecto.objects.exists()

    def test_session_is_not_accepted_in_place_of_token(self, admin_client):
        response = admin_client.post(
            reverse("api:webhook-sitio-prospectos"),
            urlencode(VALIDO),
            content_type="application/x-www-form-urlencoded",
        )

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert not Prospecto.objects.exists()


class TestIdempotency:
    def test_identical_resubmission_does_not_duplicate(self, api_client):
        first = post_form(api_client, VALIDO)
        second = post_form(api_client, VALIDO)

        assert first.status_code == HTTPStatus.CREATED
        assert second.status_code == HTTPStatus.OK
        assert second.json() == {"resultado": "duplicado"}
        assert Prospecto.objects.count() == 1

    def test_same_content_in_another_encoding_is_a_duplicate(self, api_client):
        post_form(api_client, VALIDO)

        response = api_client.post(webhook_url(), VALIDO, format="json")

        assert response.status_code == HTTPStatus.OK
        assert Prospecto.objects.count() == 1

    def test_source_submission_id_takes_precedence(self, api_client):
        post_form(api_client, {**VALIDO, "id_envio": "envio-1"})
        edited = post_form(
            api_client,
            {**VALIDO, "id_envio": "envio-1", "mensaje": "Otro"},
        )
        other = post_form(api_client, {**VALIDO, "id_envio": "envio-2"})

        assert edited.status_code == HTTPStatus.OK
        assert other.status_code == HTTPStatus.CREATED
        assert Prospecto.objects.count() == 2  # noqa: PLR2004


class TestValidation:
    def test_missing_nombre_is_rejected(self, api_client):
        data = {k: v for k, v in VALIDO.items() if k != "nombre"}

        response = post_form(api_client, data)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "nombre" in response.json()
        assert not Prospecto.objects.exists()

    def test_email_or_telefono_is_required(self, api_client):
        data = {k: v for k, v in VALIDO.items() if k not in {"email", "telefono"}}

        response = post_form(api_client, data)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "non_field_errors" in response.json()
        assert not Prospecto.objects.exists()

    def test_telefono_alone_is_enough(self, api_client):
        data = {k: v for k, v in VALIDO.items() if k != "email"}

        response = post_form(api_client, data)

        assert response.status_code == HTTPStatus.CREATED

    def test_invalid_email_is_rejected(self, api_client):
        response = post_form(api_client, {**VALIDO, "email": "no-es-un-email"})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "email" in response.json()

    def test_unknown_formato_is_rejected(self, api_client):
        response = post_form(api_client, VALIDO, url=webhook_url(formato="elementor"))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "formato" in response.json()
        assert not Prospecto.objects.exists()

    def test_json_body_must_be_an_object(self, api_client):
        response = api_client.post(webhook_url(), [VALIDO], format="json")

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert not Prospecto.objects.exists()

    def test_unknown_extra_fields_are_ignored(self, api_client):
        response = post_form(
            api_client,
            {**VALIDO, "utm_source": "google", "estado": "convertido"},
        )

        assert response.status_code == HTTPStatus.CREATED
        prospecto = Prospecto.objects.get()
        assert prospecto.estado == Prospecto.Estado.NUEVO
        assert prospecto.payload_original["utm_source"] == "google"

    def test_invalid_origen_falls_back_to_sitio(self, api_client):
        post_form(api_client, {**VALIDO, "origen": "<script>"})

        assert Prospecto.objects.get().origen == "sitio"


class TestCatalogueFlags:
    def test_unknown_service_is_stored_and_flagged(self, api_client):
        response = post_form(api_client, {**VALIDO, "servicio": "contabilidad"})

        assert response.status_code == HTTPStatus.CREATED
        prospecto = Prospecto.objects.get()
        assert prospecto.servicio_interes == "contabilidad"
        assert prospecto.servicio_desconocido
        assert prospecto.plan_desconocido

    def test_unknown_plan_is_stored_and_flagged(self, api_client):
        response = post_form(api_client, {**VALIDO, "plan": "trimestral"})

        assert response.status_code == HTTPStatus.CREATED
        prospecto = Prospecto.objects.get()
        assert prospecto.plan == "trimestral"
        assert not prospecto.servicio_desconocido
        assert prospecto.plan_desconocido

    def test_slugs_are_matched_case_insensitively(self, api_client):
        post_form(
            api_client,
            {**VALIDO, "servicio": "Domicilio-Tributario", "plan": "ANUAL"},
        )

        prospecto = Prospecto.objects.get()
        assert not prospecto.servicio_desconocido
        assert not prospecto.plan_desconocido

    def test_general_enquiry_without_service_is_not_flagged(self, api_client):
        data = {k: v for k, v in VALIDO.items() if k not in {"servicio", "plan"}}

        post_form(api_client, data)

        prospecto = Prospecto.objects.get()
        assert not prospecto.servicio_desconocido
        assert not prospecto.plan_desconocido


class TestPayloadOriginal:
    def test_original_payload_is_stored_as_received(self, api_client):
        post_form(api_client, {**VALIDO, "servicio": "Domicilio-Tributario"})

        payload = Prospecto.objects.get().payload_original
        assert payload == {**VALIDO, "servicio": "Domicilio-Tributario"}
        assert "token" not in payload


class TestThrottling:
    def test_requests_over_the_rate_get_429(self, api_client, settings):
        settings.WEBHOOK_SITIO_THROTTLE_RATE = "2/min"

        responses = [
            post_form(api_client, {**VALIDO, "id_envio": f"envio-{i}"})
            for i in range(3)
        ]

        assert [r.status_code for r in responses] == [
            HTTPStatus.CREATED,
            HTTPStatus.CREATED,
            HTTPStatus.TOO_MANY_REQUESTS,
        ]
        assert "Retry-After" in responses[-1].headers
        assert Prospecto.objects.count() == 2  # noqa: PLR2004

    def test_wrong_token_attempts_are_throttled_too(self, api_client, settings):
        settings.WEBHOOK_SITIO_THROTTLE_RATE = "2/min"
        wrong = webhook_url(token=WRONG_TOKEN)

        statuses = [
            post_form(api_client, VALIDO, url=wrong).status_code for _ in range(3)
        ]

        assert statuses == [
            HTTPStatus.FORBIDDEN,
            HTTPStatus.FORBIDDEN,
            HTTPStatus.TOO_MANY_REQUESTS,
        ]
