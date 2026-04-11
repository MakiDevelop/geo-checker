"""Unit tests for js_render_fetcher SSRF hardening (IP literal guard)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from src.fetcher.js_render_fetcher import (
    _is_private_ip_literal,
    render_js_content,
)
from src.security.url_guard import UnsafeWebhookTarget


class TestIsPrivateIpLiteral:
    """Unit tests for `_is_private_ip_literal` (the page.route() IP guard)."""

    @pytest.mark.parametrize(
        "ip",
        [
            "169.254.169.254",  # AWS / Vultr metadata
            "127.0.0.1",
            "127.255.255.255",
            "10.0.0.1",
            "10.255.255.255",
            "172.16.0.1",
            "172.31.255.255",
            "192.168.0.1",
            "192.168.255.255",
            "100.64.0.1",  # CGNAT / Tailscale
            "0.0.0.0",
            "224.0.0.1",  # multicast
        ],
    )
    def test_catches_v4_private_and_reserved(self, ip: str):
        assert _is_private_ip_literal(ip) is True

    @pytest.mark.parametrize(
        "ip",
        [
            "::1",
            "fe80::1",
            "fc00::1",
            "fd00::1",
            "::",
            "ff00::1",
        ],
    )
    def test_catches_v6_private_and_reserved(self, ip: str):
        assert _is_private_ip_literal(ip) is True

    @pytest.mark.parametrize(
        "ip",
        [
            "8.8.8.8",
            "1.1.1.1",
            "93.184.216.34",  # example.com
        ],
    )
    def test_public_v4_returns_false(self, ip: str):
        assert _is_private_ip_literal(ip) is False

    @pytest.mark.parametrize(
        "host",
        [
            "example.com",
            "gc.ranran.tw",
            "",
            "not-an-ip",
        ],
    )
    def test_hostname_returns_false(self, host: str):
        assert _is_private_ip_literal(host) is False

    def test_ipv4_mapped_v6_metadata_blocked(self):
        # ::ffff:169.254.169.254 -> IPv4-mapped IPv6 pointing at metadata
        assert _is_private_ip_literal("::ffff:169.254.169.254") is True

    def test_ipv6_brackets_stripped(self):
        assert _is_private_ip_literal("[::1]") is True
        assert _is_private_ip_literal("[2001:4860:4860::8888]") is False


class TestRenderJsContentRejectsUnsafeUrl:
    """`render_js_content` must pre-validate via url_guard before launching Chromium."""

    def test_rejects_when_url_guard_raises_unsafe(self):
        with patch(
            "src.fetcher.js_render_fetcher.resolve_webhook_target",
            side_effect=UnsafeWebhookTarget("simulated: resolves to 169.254.169.254"),
        ), pytest.raises(UnsafeWebhookTarget):
            render_js_content("http://attacker.example.com/")
