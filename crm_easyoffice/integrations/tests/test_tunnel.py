from __future__ import annotations

import httpx
import pytest

from crm_easyoffice.integrations.payment import tunnel
from crm_easyoffice.integrations.payment.base import PaymentError
from crm_easyoffice.integrations.payment.registry import webhook_base_url

METRICS = "http://tunnel:2000/quicktunnel"


def answering(monkeypatch, response: httpx.Response | Exception):
    def get(url, timeout):
        if isinstance(response, Exception):
            raise response
        response.request = httpx.Request("GET", url)
        return response

    monkeypatch.setattr(tunnel.httpx, "get", get)


def test_reads_the_tunnel_hostname(monkeypatch):
    answering(
        monkeypatch, httpx.Response(200, json={"hostname": "abc.trycloudflare.com"}),
    )

    assert tunnel.quick_tunnel_url(METRICS) == "https://abc.trycloudflare.com"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"hostname": ""}),
        httpx.Response(503),
        httpx.ConnectError("refused"),
    ],
)
def test_a_tunnel_not_up_yet_is_transient(monkeypatch, response):
    answering(monkeypatch, response)

    with pytest.raises(PaymentError) as error:
        tunnel.quick_tunnel_url(METRICS)

    assert error.value.transient


def test_a_configured_url_wins_over_the_tunnel(monkeypatch, settings):
    settings.PAYMENT_WEBHOOK_BASE_URL = "https://pagos.example.test"
    settings.PAYMENT_TUNNEL_METRICS_URL = METRICS
    answering(monkeypatch, httpx.ConnectError("not called"))

    assert webhook_base_url() == "https://pagos.example.test"


def test_the_tunnel_is_used_when_no_url_is_configured(monkeypatch, settings):
    settings.PAYMENT_WEBHOOK_BASE_URL = ""
    settings.PAYMENT_TUNNEL_METRICS_URL = METRICS
    answering(
        monkeypatch, httpx.Response(200, json={"hostname": "abc.trycloudflare.com"}),
    )

    assert webhook_base_url() == "https://abc.trycloudflare.com"
