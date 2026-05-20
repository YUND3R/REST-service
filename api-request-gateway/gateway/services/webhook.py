from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import socket
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


class UnsafeWebhookUrl(ValueError):
    pass


def _allowed_hosts() -> set[str]:
    raw = os.getenv("WEBHOOK_ALLOWED_HOSTS", "").strip()
    return {host.strip().lower() for host in raw.split(",") if host.strip()}


def _safe_url_label(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "<invalid>").lower()
    port = f":{parsed.port}" if parsed.port else ""
    scheme = parsed.scheme or "<unknown>"
    return f"{scheme}://{host}{port}"


def _is_forbidden_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified


async def _resolve_host(host: str, port: int) -> list[str]:
    def resolve() -> list[str]:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        return [info[4][0] for info in infos]

    return await asyncio.to_thread(resolve)


async def validate_webhook_destination(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeWebhookUrl("webhook URL scheme must be http or https")
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host or host == "localhost" or host.endswith(".localhost"):
        raise UnsafeWebhookUrl("webhook host must not be loopback/internal")

    allowed = _allowed_hosts()
    if allowed and host not in allowed and not any(host.endswith(f".{allowed_host}") for allowed_host in allowed):
        raise UnsafeWebhookUrl("webhook host is not allowlisted")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        literal_ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal_ip = None
    if literal_ip is not None:
        if _is_forbidden_ip(str(literal_ip)):
            raise UnsafeWebhookUrl("webhook host resolves to a forbidden IP range")
        return

    try:
        resolved = await _resolve_host(host, port)
    except OSError as exc:
        raise UnsafeWebhookUrl("webhook host could not be resolved") from exc
    if not resolved:
        raise UnsafeWebhookUrl("webhook host did not resolve")
    for address in resolved:
        if _is_forbidden_ip(address):
            raise UnsafeWebhookUrl("webhook host resolves to a forbidden IP range")


async def deliver_webhook(url: str, body: dict, *, timeout: float = 30.0) -> None:
    try:
        await validate_webhook_destination(url)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await client.post(url, json=body)
            response.raise_for_status()
    except UnsafeWebhookUrl:
        logger.warning("Unsafe webhook URL blocked: %s", _safe_url_label(url))
    except Exception:
        logger.exception("Webhook delivery failed: %s", _safe_url_label(url))
