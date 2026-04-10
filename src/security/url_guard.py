"""Outbound URL validation, resolution, and SSRF-safe fetching helpers."""
from __future__ import annotations

import socket
import sys
from dataclasses import dataclass
from ipaddress import ip_address, ip_network
from urllib.parse import unquote, urljoin, urlparse

import requests
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import HTTPError as Urllib3HTTPError
from urllib3.util import Timeout

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
    respect_allowlist: bool = True,
) -> ResolvedWebhookTarget:
    """Resolve an outbound HTTP target with SSRF guard.

    Used by both webhook delivery (allowlist enabled) and the analyse fetcher
    (allowlist disabled — every request is user-supplied and never trusted).
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise WebhookValidationError("URL must start with http:// or https://")

    hostname = _normalize_hostname(parsed.hostname)
    if not hostname:
        raise WebhookValidationError("Invalid URL: hostname not found")

    try:
        parsed_port = parsed.port
    except ValueError as exc:
        # Out-of-range or non-numeric port → bubble up as a validation error
        # instead of leaking the bare ValueError to callers (would 500 the API).
        raise WebhookValidationError(f"Invalid URL port: {exc}") from exc

    port = parsed_port or (443 if parsed.scheme == "https" else 80)
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

        reason = _classify_ip(hostname, ip_str, respect_allowlist=respect_allowlist)
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


def _classify_ip(hostname: str, ip_str: str, *, respect_allowlist: bool = True) -> str:
    if respect_allowlist and _hostname_allowlisted(hostname):
        return ""

    try:
        ip = ip_address(ip_str)
    except ValueError:
        return f"Invalid IP address: {ip_str}"

    mapped_ip = getattr(ip, "ipv4_mapped", None)
    if respect_allowlist and (
        _ip_allowlisted(ip)
        or (mapped_ip is not None and _ip_allowlisted(mapped_ip))
    ):
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


# ---------------------------------------------------------------------------
# SSRF-safe outbound fetcher (used by html_fetcher and any other code path
# that needs to fetch a user-supplied URL without trusting DNS resolution
# at request time).
# ---------------------------------------------------------------------------


_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


@dataclass
class PinnedFetchResult:
    """Outcome of a single SSRF-safe fetch (after any redirects)."""

    final_url: str
    status: int
    headers: dict[str, str]
    body: bytes


def _build_pool(target: ResolvedWebhookTarget, timeout_seconds: float):
    """Construct a one-shot urllib3 ConnectionPool aimed at a pinned IP."""
    timeout = Timeout(total=timeout_seconds)
    if target.scheme == "https":
        return HTTPSConnectionPool(
            host=target.pinned_ip,
            port=target.port,
            timeout=timeout,
            maxsize=1,
            retries=False,
            assert_hostname=target.hostname,
            server_hostname=target.hostname,
            cert_reqs="CERT_REQUIRED",
            ca_certs=requests.certs.where(),
        )
    return HTTPConnectionPool(
        host=target.pinned_ip,
        port=target.port,
        timeout=timeout,
        maxsize=1,
        retries=False,
    )


def pinned_fetch(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout_seconds: float = 15.0,
    max_size: int = 10 * 1024 * 1024,
    max_redirects: int = 5,
) -> PinnedFetchResult:
    """Fetch a URL with SSRF guard + IP pinning + redirect re-validation.

    Each hop (initial + every redirect) re-runs `resolve_webhook_target` with
    `respect_allowlist=False`, so any leg that resolves to a private/metadata
    IP is rejected before any TCP packet leaves the host. The actual TCP
    connection always targets the pinned IP from validation time, so DNS
    rebinding between validate and connect is impossible (the server cannot
    swap the IP under us between calls).

    Raises:
        WebhookValidationError / UnsafeWebhookTarget: SSRF guard rejected
            the original URL or any redirect target.
        ValueError: response exceeds `max_size` or redirect chain is broken.
        Urllib3HTTPError / OSError: network/TLS failure.
    """
    request_headers = dict(headers or {})
    current_url = url

    for hop in range(max_redirects + 1):
        target = resolve_webhook_target(current_url, respect_allowlist=False)
        pool = _build_pool(target, timeout_seconds)
        response = None
        try:
            request_headers["Host"] = target.host_header
            if target.authorization_header:
                request_headers.setdefault("Authorization", target.authorization_header)

            response = pool.urlopen(
                "GET",
                target.path_and_query,
                headers=request_headers,
                redirect=False,
                preload_content=False,
            )

            status = response.status
            resp_headers = dict(response.headers)

            if status in _REDIRECT_STATUSES and hop < max_redirects:
                location = resp_headers.get("Location", "")
                if not location:
                    raise ValueError("Redirect response missing Location header")
                response.release_conn()
                response = None
                current_url = urljoin(current_url, location)
                continue

            content_length = resp_headers.get("Content-Length")
            if content_length and content_length.strip().isdigit():
                if int(content_length) > max_size:
                    raise ValueError(
                        f"Response too large: {int(content_length)} bytes "
                        f"(max {max_size})"
                    )

            body = bytearray()
            for chunk in response.stream(8192, decode_content=True):
                body.extend(chunk)
                if len(body) > max_size:
                    raise ValueError(
                        f"Response too large: exceeded {max_size} bytes"
                    )

            return PinnedFetchResult(
                final_url=current_url,
                status=status,
                headers=resp_headers,
                body=bytes(body),
            )
        finally:
            if response is not None:
                response.release_conn()
            pool.close()

    raise ValueError(f"Too many redirects (>{max_redirects})")


__all__ = [
    "PinnedFetchResult",
    "ResolvedWebhookTarget",
    "UnsafeWebhookTarget",
    "Urllib3HTTPError",
    "WebhookValidationError",
    "pinned_fetch",
    "resolve_webhook_target",
    "validate_webhook_url",
]
