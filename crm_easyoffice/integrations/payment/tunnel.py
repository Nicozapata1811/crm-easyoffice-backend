"""Public URL of the local cloudflared quick tunnel, for development only."""

from __future__ import annotations

import httpx

from .base import PaymentError

TUNNEL_CAIDO = (
    "The local tunnel has no live connection (quick tunnels expire after a "
    "while). Run `docker compose -f docker-compose.local.yml restart tunnel`."
)


def quick_tunnel_url(metrics_url: str) -> str:
    """Ask cloudflared's metrics server which random hostname it got.

    A quick tunnel keeps reporting its hostname after Cloudflare has dropped
    it, so the hostname is only trusted while ``/ready`` reports a live
    connection.

    Raises:
        PaymentError: The tunnel is not up yet, worth retrying, or is down.
    """
    base = metrics_url.rsplit("/", 1)[0]
    try:
        hostname = (
            httpx.get(metrics_url, timeout=3).raise_for_status().json()["hostname"]
        )
        ready = httpx.get(f"{base}/ready", timeout=3)
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        msg = f"The local tunnel did not report its URL: {exc}"
        raise PaymentError(msg, transient=True) from exc
    if not hostname:
        msg = "The local tunnel has no URL yet."
        raise PaymentError(msg, transient=True)
    if ready.status_code != httpx.codes.OK:
        raise PaymentError(TUNNEL_CAIDO)
    return f"https://{hostname}"
