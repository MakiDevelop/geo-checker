"""Unit tests for HTML fetcher module with security focus."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from src.fetcher.html_fetcher import (
    MAX_RESPONSE_SIZE,
    _is_url,
    _needs_js_render,
    _resolve_and_validate_url,
    _validate_ip,
    fetch_html,
)


class TestURLValidation:
    """Tests for URL validation."""

    def test_valid_http_url(self):
        """HTTP URLs should be valid."""
        assert _is_url("http://example.com") is True

    def test_valid_https_url(self):
        """HTTPS URLs should be valid."""
        assert _is_url("https://example.com") is True

    def test_invalid_file_scheme(self):
        """File scheme should be invalid."""
        assert _is_url("file:///etc/passwd") is False

    def test_invalid_no_scheme(self):
        """URLs without scheme should be invalid."""
        assert _is_url("example.com") is False

    def test_invalid_javascript_scheme(self):
        """JavaScript scheme should be invalid."""
        assert _is_url("javascript:alert(1)") is False

    def test_invalid_data_scheme(self):
        """Data scheme should be invalid."""
        assert _is_url("data:text/html,<script>alert(1)</script>") is False

    def test_invalid_ftp_scheme(self):
        """FTP scheme should be invalid."""
        assert _is_url("ftp://files.example.com/file.txt") is False


class TestIPValidation:
    """Tests for IP address validation (SSRF protection)."""

    def test_public_ip_allowed(self):
        """Public IPs should be allowed."""
        is_safe, error = _validate_ip("8.8.8.8")
        assert is_safe is True
        assert error == ""

    def test_public_ip_cloudflare(self):
        """Cloudflare DNS IP should be allowed."""
        is_safe, error = _validate_ip("1.1.1.1")
        assert is_safe is True

    @pytest.mark.parametrize(
        "ip",
        [
            "192.168.0.1",
            "192.168.1.1",
            "192.168.100.100",
            "192.168.255.255",
        ],
    )
    def test_private_ip_blocked_192(self, ip):
        """192.168.x.x should be blocked."""
        is_safe, error = _validate_ip(ip)
        assert is_safe is False
        assert "private" in error.lower()

    @pytest.mark.parametrize(
        "ip",
        [
            "10.0.0.1",
            "10.10.10.10",
            "10.255.255.255",
        ],
    )
    def test_private_ip_blocked_10(self, ip):
        """10.x.x.x should be blocked."""
        is_safe, error = _validate_ip(ip)
        assert is_safe is False
        assert "private" in error.lower()

    @pytest.mark.parametrize(
        "ip",
        [
            "172.16.0.1",
            "172.20.0.1",
            "172.31.255.255",
        ],
    )
    def test_private_ip_blocked_172(self, ip):
        """172.16-31.x.x should be blocked."""
        is_safe, error = _validate_ip(ip)
        assert is_safe is False
        assert "private" in error.lower()

    @pytest.mark.parametrize(
        "ip",
        [
            "127.0.0.1",
            "127.0.0.2",
            "127.255.255.255",
        ],
    )
    def test_localhost_blocked_127(self, ip):
        """127.x.x.x (localhost) should be blocked."""
        is_safe, error = _validate_ip(ip)
        assert is_safe is False

    @pytest.mark.parametrize(
        "ip",
        [
            "169.254.1.1",
            "169.254.169.254",  # AWS metadata endpoint
        ],
    )
    def test_link_local_blocked(self, ip):
        """169.254.x.x (link-local/AWS metadata) should be blocked."""
        is_safe, error = _validate_ip(ip)
        assert is_safe is False

    def test_invalid_ip_format(self):
        """Invalid IP format should return error."""
        is_safe, error = _validate_ip("not-an-ip")
        assert is_safe is False
        assert "invalid" in error.lower()

    def test_ipv6_localhost_blocked(self):
        """IPv6 localhost should be blocked."""
        is_safe, error = _validate_ip("::1")
        assert is_safe is False

    def test_ipv6_private_blocked(self):
        """IPv6 private addresses should be blocked."""
        is_safe, error = _validate_ip("fd00::1")
        assert is_safe is False

    def test_zero_ip_blocked(self):
        """0.0.0.0 should be blocked."""
        is_safe, error = _validate_ip("0.0.0.0")
        assert is_safe is False


class TestURLResolution:
    """Tests for URL resolution and validation."""

    def test_resolve_invalid_scheme(self):
        """Invalid scheme should return error."""
        ip, hostname, error = _resolve_and_validate_url("ftp://example.com")
        assert error != ""
        assert "scheme" in error.lower()

    def test_resolve_missing_hostname(self):
        """Missing hostname should return error."""
        ip, hostname, error = _resolve_and_validate_url("http://")
        assert error != ""
        assert ip == ""

    def test_resolve_file_scheme_rejected(self):
        """File scheme should be rejected."""
        ip, hostname, error = _resolve_and_validate_url("file:///etc/passwd")
        assert error != ""
        assert "scheme" in error.lower()

    @patch("socket.gethostbyname")
    def test_resolve_public_ip_allowed(self, mock_dns):
        """Public IP resolution should be allowed."""
        mock_dns.return_value = "93.184.216.34"  # example.com
        ip, hostname, error = _resolve_and_validate_url("https://example.com")
        assert error == ""
        assert ip == "93.184.216.34"
        assert hostname == "example.com"

    @patch("socket.gethostbyname")
    def test_resolve_private_ip_blocked(self, mock_dns):
        """DNS resolving to private IP should be blocked."""
        mock_dns.return_value = "192.168.1.1"
        ip, hostname, error = _resolve_and_validate_url("https://evil.com")
        assert error != ""
        assert "private" in error.lower()

    @patch("socket.gethostbyname")
    def test_resolve_localhost_blocked(self, mock_dns):
        """DNS resolving to localhost should be blocked."""
        mock_dns.return_value = "127.0.0.1"
        ip, hostname, error = _resolve_and_validate_url("https://localhost.evil.com")
        assert error != ""

    @patch("socket.gethostbyname")
    def test_resolve_aws_metadata_blocked(self, mock_dns):
        """DNS resolving to AWS metadata IP should be blocked."""
        mock_dns.return_value = "169.254.169.254"
        ip, hostname, error = _resolve_and_validate_url("https://metadata.evil.com")
        assert error != ""

    @patch("socket.gethostbyname")
    def test_resolve_dns_failure(self, mock_dns):
        """DNS resolution failure should return error."""
        import socket

        mock_dns.side_effect = socket.gaierror("DNS lookup failed")
        ip, hostname, error = _resolve_and_validate_url("https://nonexistent.invalid")
        assert error != ""
        assert "resolve" in error.lower()


class TestSSRFProtection:
    """Integration tests for SSRF protection in fetch_html."""

    def test_file_path_rejected(self):
        """File paths should be rejected."""
        with pytest.raises(ValueError, match="Only http"):
            fetch_html("/etc/passwd")

    def test_file_url_rejected(self):
        """File URLs should be rejected."""
        with pytest.raises(ValueError, match="Only http"):
            fetch_html("file:///etc/passwd")

    def test_javascript_url_rejected(self):
        """JavaScript URLs should be rejected."""
        with pytest.raises(ValueError, match="Only http"):
            fetch_html("javascript:alert(1)")

    @patch("socket.gethostbyname")
    def test_localhost_url_rejected(self, mock_dns):
        """Localhost URLs should be rejected."""
        mock_dns.return_value = "127.0.0.1"
        with pytest.raises(ValueError, match="SSRF protection"):
            fetch_html("http://localhost/admin")

    @patch("socket.gethostbyname")
    def test_internal_ip_url_rejected(self, mock_dns):
        """Direct internal IP URLs should be rejected."""
        mock_dns.return_value = "10.0.0.5"
        with pytest.raises(ValueError, match="SSRF protection"):
            fetch_html("http://10.0.0.5/secret")

    @patch("socket.gethostbyname")
    def test_aws_metadata_rejected(self, mock_dns):
        """AWS metadata endpoint should be rejected."""
        mock_dns.return_value = "169.254.169.254"
        with pytest.raises(ValueError, match="SSRF protection"):
            fetch_html("http://169.254.169.254/latest/meta-data/")

    @patch("socket.gethostbyname")
    @patch("requests.get")
    def test_redirect_to_internal_ip_blocked(self, mock_get, mock_dns):
        """Redirect to internal IP should be blocked."""
        # First request succeeds, returns redirect
        mock_response = MagicMock()
        mock_response.is_redirect = True
        mock_response.headers = {"Location": "http://192.168.1.1/admin"}
        mock_get.return_value = mock_response

        # DNS for original URL resolves to public IP
        # DNS for redirect target resolves to private IP
        mock_dns.side_effect = ["93.184.216.34", "192.168.1.1"]

        with pytest.raises(ValueError, match="SSRF protection"):
            fetch_html("https://example.com/redirect")

    @patch("socket.gethostbyname")
    @patch("requests.get")
    def test_redirect_to_localhost_blocked(self, mock_get, mock_dns):
        """Redirect to localhost should be blocked."""
        mock_response = MagicMock()
        mock_response.is_redirect = True
        mock_response.headers = {"Location": "http://127.0.0.1:8080/internal"}
        mock_get.return_value = mock_response

        mock_dns.side_effect = ["93.184.216.34", "127.0.0.1"]

        with pytest.raises(ValueError, match="SSRF protection"):
            fetch_html("https://example.com/evil-redirect")


class TestResponseSizeLimits:
    """Tests for response size limiting."""

    @patch("socket.gethostbyname")
    @patch("requests.get")
    def test_large_content_length_rejected(self, mock_get, mock_dns):
        """Response with Content-Length exceeding limit should be rejected."""
        mock_dns.return_value = "93.184.216.34"

        mock_response = MagicMock()
        mock_response.is_redirect = False
        mock_response.headers = {"Content-Length": str(MAX_RESPONSE_SIZE + 1)}
        mock_response.close = MagicMock()
        mock_get.return_value = mock_response

        with pytest.raises(ValueError, match="too large"):
            fetch_html("https://example.com/huge-file")

    @patch("socket.gethostbyname")
    @patch("requests.get")
    def test_chunked_response_too_large_rejected(self, mock_get, mock_dns):
        """Chunked response exceeding limit should be rejected."""
        mock_dns.return_value = "93.184.216.34"

        mock_response = MagicMock()
        mock_response.is_redirect = False
        mock_response.headers = {}  # No Content-Length
        mock_response.raise_for_status = MagicMock()
        mock_response.close = MagicMock()

        # Generate chunks that exceed limit
        def generate_large_chunks():
            chunk_size = 1024 * 1024  # 1MB chunks
            for _ in range(15):  # 15MB total > 10MB limit
                yield b"x" * chunk_size

        mock_response.iter_content.return_value = generate_large_chunks()
        mock_get.return_value = mock_response

        with pytest.raises(ValueError, match="too large"):
            fetch_html("https://example.com/streaming-huge")


class TestJSRenderDetection:
    """Tests for JavaScript render detection."""

    def test_js_required_message_triggers_render(self):
        """Pages with 'JavaScript must be enabled' should trigger JS render."""
        html = "<html><body>JavaScript must be enabled to view this page</body></html>"
        assert _needs_js_render(html, "text/html") is True

    def test_non_html_content_type_triggers_render(self):
        """Non-HTML content type should trigger JS render."""
        html = "<html><body>Content</body></html>"
        assert _needs_js_render(html, "application/json") is True

    def test_short_html_without_content_triggers_render(self):
        """Short HTML without paragraphs or headings should trigger JS render."""
        html = "<html><body><div id='app'></div></body></html>"
        assert _needs_js_render(html, "text/html") is True

    def test_normal_html_does_not_trigger_render(self):
        """Normal HTML with content should not trigger JS render."""
        html = """
        <html>
        <head><title>Test</title></head>
        <body>
            <h1>Welcome</h1>
            <p>This is a paragraph with some content that makes it longer.</p>
            <p>Another paragraph here.</p>
        </body>
        </html>
        """ * 10  # Make it longer than 2000 chars
        assert _needs_js_render(html, "text/html") is False


class TestHTTPErrors:
    """Tests for HTTP error handling."""

    @patch("socket.gethostbyname")
    @patch("requests.get")
    def test_http_404_raises_error(self, mock_get, mock_dns):
        """HTTP 404 should raise an error."""
        mock_dns.return_value = "93.184.216.34"

        mock_response = MagicMock()
        mock_response.is_redirect = False
        mock_response.headers = {}
        mock_response.raise_for_status.side_effect = requests.HTTPError("404 Not Found")
        mock_get.return_value = mock_response

        with pytest.raises(requests.HTTPError):
            fetch_html("https://example.com/not-found")

    @patch("socket.gethostbyname")
    @patch("requests.get")
    def test_http_500_raises_error(self, mock_get, mock_dns):
        """HTTP 500 should raise an error."""
        mock_dns.return_value = "93.184.216.34"

        mock_response = MagicMock()
        mock_response.is_redirect = False
        mock_response.headers = {}
        mock_response.raise_for_status.side_effect = requests.HTTPError(
            "500 Internal Server Error"
        )
        mock_get.return_value = mock_response

        with pytest.raises(requests.HTTPError):
            fetch_html("https://example.com/error")

    @patch("socket.gethostbyname")
    @patch("requests.get")
    def test_connection_timeout(self, mock_get, mock_dns):
        """Connection timeout should raise an error."""
        mock_dns.return_value = "93.184.216.34"
        mock_get.side_effect = requests.Timeout("Connection timed out")

        with pytest.raises(requests.Timeout):
            fetch_html("https://slow.example.com")
