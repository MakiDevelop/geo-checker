"""Tests for webhook URL validation and pinning resolution."""
from __future__ import annotations

import socket

import pytest

from src.config.settings import settings
from src.security.url_guard import resolve_webhook_target, validate_webhook_url


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


@pytest.fixture(autouse=True)
def reset_allowlists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings.security, "webhook_host_allowlist", [])
    monkeypatch.setattr(settings.security, "webhook_cidr_allowlist", [])


@pytest.mark.parametrize(
    "ip_str",
    [
        "10.1.2.3",
        "172.16.5.4",
        "192.168.1.2",
        "127.0.0.1",
        "169.254.10.10",
        "100.64.0.8",
        "0.0.0.5",
        "224.0.0.1",
        "240.0.0.1",
        "::1",
        "fe80::1",
        "fc00::1",
        "::",
        "ff00::1",
        "::ffff:192.168.1.10",
    ],
)
def test_validate_webhook_url_blocks_denylisted_ranges(
    ip_str: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: _addrinfo_for(ip_str),
    )

    is_valid, reason = validate_webhook_url("https://hooks.example.com/test")

    assert is_valid is False
    assert reason


def test_validate_webhook_url_rejects_non_http_scheme() -> None:
    is_valid, reason = validate_webhook_url("ftp://hooks.example.com/test")

    assert is_valid is False
    assert reason == "URL must start with http:// or https://"


def test_validate_webhook_url_accepts_public_https_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: _addrinfo_for("8.8.8.8"),
    )

    is_valid, reason = validate_webhook_url("https://hooks.example.com/test?via=1")
    target = resolve_webhook_target("https://hooks.example.com/test?via=1")

    assert is_valid is True
    assert reason == ""
    assert target.pinned_ip == "8.8.8.8"
    assert target.host_header == "hooks.example.com"
    assert target.path_and_query == "/test?via=1"


def test_cidr_allowlist_can_bypass_blocked_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: _addrinfo_for("100.64.1.20"),
    )
    monkeypatch.setattr(settings.security, "webhook_cidr_allowlist", ["100.64.0.0/10"])

    is_valid, reason = validate_webhook_url("https://hooks.example.com/test")

    assert is_valid is True
    assert reason == ""


def test_host_allowlist_can_bypass_blocked_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: _addrinfo_for("127.0.0.1"),
    )
    monkeypatch.setattr(settings.security, "webhook_host_allowlist", ["hooks.example.com"])

    is_valid, reason = validate_webhook_url("https://hooks.example.com/test")

    assert is_valid is True
    assert reason == ""


def test_respect_allowlist_false_ignores_host_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fetch path passes respect_allowlist=False; allowlist must NOT bypass IP check."""
    from src.security.url_guard import UnsafeWebhookTarget, resolve_webhook_target

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: _addrinfo_for("127.0.0.1"),
    )
    monkeypatch.setattr(settings.security, "webhook_host_allowlist", ["evil.example.com"])
    monkeypatch.setattr(settings.security, "webhook_cidr_allowlist", ["127.0.0.0/8"])

    with pytest.raises(UnsafeWebhookTarget):
        resolve_webhook_target(
            "https://evil.example.com/x",
            respect_allowlist=False,
        )


def test_invalid_port_returns_validation_error() -> None:
    """Out-of-range port must surface as WebhookValidationError, not ValueError."""
    from src.security.url_guard import WebhookValidationError, validate_webhook_url

    is_valid, reason = validate_webhook_url("https://hooks.example.com:99999/x")
    assert is_valid is False
    assert "port" in reason.lower()

    # also confirm resolve_webhook_target raises the right type
    from src.security.url_guard import resolve_webhook_target
    with pytest.raises(WebhookValidationError):
        resolve_webhook_target("https://hooks.example.com:99999/x")
