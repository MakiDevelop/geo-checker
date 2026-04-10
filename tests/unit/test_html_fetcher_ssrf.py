"""SSRF regression tests for the HTML fetcher pipeline.

These tests assert that fetch_html refuses to issue any outbound request
when DNS resolution returns a private/internal IP, regardless of which
hostname the user passes in. This is the regression guard for the
DNS-rebinding TOCTOU that existed in the pre-pin implementation.
"""
from __future__ import annotations

import socket

import pytest


def _addrinfo_for(ip_str: str, port: int = 443):
    if ":" in ip_str:
        return [
            (
                socket.AF_INET6,
                socket.SOCK_STREAM,
                6,
                "",
                (ip_str, port, 0, 0),
            )
        ]
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip_str, port))]


@pytest.mark.parametrize(
    "ip_str",
    [
        "127.0.0.1",
        "169.254.169.254",  # cloud metadata
        "10.0.0.5",
        "192.168.1.10",
        "172.16.5.4",
        "100.64.0.5",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:127.0.0.1",
    ],
)
def test_fetch_html_blocks_private_ip(
    ip_str: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fetch_html must reject any URL whose hostname resolves to a denylist IP."""
    from src.fetcher import html_fetcher
    from src.security import url_guard

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: _addrinfo_for(ip_str),
    )
    # also patch the symbol url_guard imported at module load
    monkeypatch.setattr(
        url_guard.socket,
        "getaddrinfo",
        lambda *args, **kwargs: _addrinfo_for(ip_str),
    )

    with pytest.raises(ValueError, match="SSRF protection"):
        html_fetcher.fetch_html("https://attacker.example.com/")


def test_fetch_html_rejects_non_http_scheme() -> None:
    from src.fetcher import html_fetcher

    with pytest.raises(ValueError, match="http and https"):
        html_fetcher.fetch_html("file:///etc/passwd")


def test_fetch_html_rejects_invalid_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """A URL with out-of-range port must surface as a SSRF protection error,
    not a bare ValueError leaking from urlparse."""
    from src.fetcher import html_fetcher

    with pytest.raises(ValueError, match="SSRF protection"):
        html_fetcher.fetch_html("https://attacker.example.com:99999/")
