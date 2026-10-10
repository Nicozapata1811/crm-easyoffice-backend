"""Public URL of the local cloudflared quick tunnel, for development only."""

from __future__ import annotations

import httpx

from .base import PaymentError


def quick_tunnel_url(metrics_url: str) -> str:
    """Ask cloudflared's metrics server which random hostname it got.

    Raises:
        PaymentError: The tunnel is not up yet; worth retrying.
    """
    try:
        hostname = (
            httpx.get(metrics_url, timeout=3).raise_for_status().json()["hostname"]
        )
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        msg = f"The local tunnel did not report its URL: {exc}"
        raise PaymentError(msg, transient=True) from exc
    if not hostname:
        msg = "The local tunnel has no URL yet."
        raise PaymentError(msg, transient=True)
    return f"https://{hostname}"
