"""Webhook URL validation and resolution helpers."""
from __future__ import annotations

import socket
import sys
from dataclasses import dataclass
from ipaddress import ip_address, ip_network
from urllib.parse import unquote, urlparse

from src.config.settings import settings

_DENYLIST_IPV4 = (
    ip_network("10.0.0.0/8"),
    ip_network("172.16.0.0/12"),
    ip_network("192.168.0.0/16"),
    ip_network("127.0.0.0/8"),
    ip_network("169.254.0.0/16"),
    ip_network("100.64.0.0/10"),
    ip_network("0.0.0.0/8"),
    ip_network("224.0.0.0/4"),
    ip_network("240.0.0.0/4"),
)

_DENYLIST_IPV6 = (
    ip_network("::1/128"),
    ip_network("fe80::/10"),
    ip_network("fc00::/7"),
    ip_network("::/128"),
    ip_network("ff00::/8"),
)


class WebhookValidationError(ValueError):
    """Raised when a webhook URL cannot be validated."""


class UnsafeWebhookTarget(WebhookValidationError):
    """Raised when a webhook resolves to a blocked target."""


@dataclass(frozen=True)
class ResolvedWebhookTarget:
    """Parsed and resolved webhook target with a pinned destination IP."""

    original_url: str
    scheme: str
    hostname: str
    host_header: str
    port: int
    path_and_query: str
    resolved_ips: tuple[str, ...]
    pinned_ip: str
    authorization_header: str | None = None
    unsafe_reason: str = ""


def validate_webhook_url(url: str) -> tuple[bool, str]:
    """Return whether the webhook URL is valid and safe to use."""
    try:
        resolve_webhook_target(url)
    except WebhookValidationError as exc:
        return False, str(exc)
    return True, ""


def resolve_webhook_target(
    url: str,
    *,
    allow_unsafe_network: bool = False,
) -> ResolvedWebhookTarget:
    """Resolve a webhook target and optionally allow blocked networks."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise WebhookValidationError("webhook_url must start with http:// or https://")

    hostname = _normalize_hostname(parsed.hostname)
    if not hostname:
        raise WebhookValidationError("Invalid webhook URL: hostname not found")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path_and_query = parsed.path or "/"
    if parsed.query:
        path_and_query = f"{path_and_query}?{parsed.query}"

    try:
        addrinfos = socket.getaddrinfo(
            hostname,
            port,
            socket.AF_UNSPEC,
            socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise WebhookValidationError(f"Could not resolve hostname: {hostname}") from exc

    if not addrinfos:
        raise WebhookValidationError(f"Could not resolve hostname: {hostname}")

    resolved_ips: list[str] = []
    seen: set[str] = set()
    unsafe_reason = ""
    for _family, _type, _proto, _canonname, sockaddr in addrinfos:
        ip_str = str(sockaddr[0])
        if ip_str in seen:
            continue
        seen.add(ip_str)
        resolved_ips.append(ip_str)

        reason = _classify_ip(hostname, ip_str)
        if reason and not unsafe_reason:
            unsafe_reason = reason

    if not resolved_ips:
        raise WebhookValidationError(f"Could not resolve hostname: {hostname}")

    if unsafe_reason and not allow_unsafe_network:
        raise UnsafeWebhookTarget(unsafe_reason)

    return ResolvedWebhookTarget(
        original_url=url,
        scheme=parsed.scheme,
        hostname=hostname,
        host_header=_build_host_header(parsed),
        port=port,
        path_and_query=path_and_query,
        resolved_ips=tuple(resolved_ips),
        pinned_ip=resolved_ips[0],
        authorization_header=_build_basic_auth_header(parsed.username, parsed.password),
        unsafe_reason=unsafe_reason,
    )


def _normalize_hostname(hostname: str | None) -> str:
    if not hostname:
        return ""
    return hostname.rstrip(".").lower()


def _build_host_header(parsed) -> str:
    host_header = parsed.netloc.rsplit("@", 1)[-1]
    return host_header or _normalize_hostname(parsed.hostname)


def _build_basic_auth_header(username: str | None, password: str | None) -> str | None:
    if username is None and password is None:
        return None

    import base64

    raw_username = unquote(username or "")
    raw_password = unquote(password or "")
    token = base64.b64encode(f"{raw_username}:{raw_password}".encode()).decode("ascii")
    return f"Basic {token}"


def _classify_ip(hostname: str, ip_str: str) -> str:
    if _hostname_allowlisted(hostname):
        return ""

    try:
        ip = ip_address(ip_str)
    except ValueError:
        return f"Invalid IP address: {ip_str}"

    mapped_ip = getattr(ip, "ipv4_mapped", None)
    if _ip_allowlisted(ip) or (mapped_ip is not None and _ip_allowlisted(mapped_ip)):
        return ""

    if mapped_ip is not None:
        return f"Access to IPv4-mapped IPv6 webhook targets is forbidden: {ip_str}"

    denylist = _DENYLIST_IPV4 if ip.version == 4 else _DENYLIST_IPV6
    for network in denylist:
        if ip in network:
            return f"Access to internal webhook targets is forbidden: {ip_str} is in {network}"

    return ""


def _hostname_allowlisted(hostname: str) -> bool:
    normalized = _normalize_hostname(hostname)
    return normalized in {
        _normalize_hostname(entry)
        for entry in settings.security.webhook_host_allowlist
        if entry.strip()
    }


def _ip_allowlisted(ip) -> bool:
    for cidr in settings.security.webhook_cidr_allowlist:
        try:
            network = ip_network(cidr, strict=False)
        except ValueError:
            print(
                f"[webhook-guard] ignoring invalid allowlist CIDR: {cidr}",
                file=sys.stderr,
            )
            continue
        if ip in network:
            return True
    return False
