"""Unit tests for HTML fetcher helpers.

Scope:
- URL scheme validation (`_is_url`)
- JavaScript render detection (`_needs_js_render`)

SSRF / IP denylist / redirect chain handling moved to `src/security/url_guard.py`
after the 2026-04 Phase 1 hardening and are covered by `test_url_guard.py`
and `test_html_fetcher_ssrf.py`. This file intentionally does not duplicate
those.
"""
from __future__ import annotations

from src.fetcher.html_fetcher import _is_url, _needs_js_render


class TestURLValidation:
    """Tests for URL scheme validation."""

    def test_valid_http_url(self):
        assert _is_url("http://example.com") is True

    def test_valid_https_url(self):
        assert _is_url("https://example.com") is True

    def test_invalid_file_scheme(self):
        assert _is_url("file:///etc/passwd") is False

    def test_invalid_no_scheme(self):
        assert _is_url("example.com") is False

    def test_invalid_javascript_scheme(self):
        assert _is_url("javascript:alert(1)") is False

    def test_invalid_data_scheme(self):
        assert _is_url("data:text/html,<script>alert(1)</script>") is False

    def test_invalid_ftp_scheme(self):
        assert _is_url("ftp://files.example.com/file.txt") is False


class TestJSRenderDetection:
    """Tests for JavaScript render detection heuristics."""

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
        """Normal HTML with real content should not trigger JS render."""
        html = (
            """
        <html>
        <head><title>Test</title></head>
        <body>
            <h1>Welcome</h1>
            <p>This is a paragraph with some content that makes it longer.</p>
            <p>Another paragraph here.</p>
        </body>
        </html>
        """
            * 10
        )
        assert _needs_js_render(html, "text/html") is False
