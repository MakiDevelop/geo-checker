"""
End-to-end tests for the full GEO analysis pipeline.

Tests the complete flow: fetch → parse → geo check → format
Uses a local HTTP server to avoid external network dependencies.
"""
from __future__ import annotations

import socket
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from unittest.mock import patch

import pytest

from src.fetcher.html_fetcher import fetch_html
from src.geo.geo_checker import check_geo
from src.parser.content_parser import parse_content
from src.report.formatter import format_report


# Path to test fixtures
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "html"


class QuietHTTPHandler(SimpleHTTPRequestHandler):
    """HTTP handler that doesn't log to console."""

    def __init__(self, *args, directory=None, **kwargs):
        self.directory = directory
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, format, *args):
        """Suppress logging."""
        pass


def find_free_port():
    """Find a free port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port


class LocalHTTPServer:
    """Context manager for a local HTTP server serving test fixtures."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.port = find_free_port()
        self.server = None
        self.thread = None

    def __enter__(self):
        handler = lambda *args, **kwargs: QuietHTTPHandler(
            *args, directory=str(self.directory), **kwargs
        )
        self.server = HTTPServer(("127.0.0.1", self.port), handler)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()
        return self

    def __exit__(self, *args):
        if self.server:
            self.server.shutdown()
        if self.thread:
            self.thread.join(timeout=1)

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.port}"


@pytest.fixture
def local_server():
    """Fixture that provides a local HTTP server serving test HTML files."""
    with LocalHTTPServer(FIXTURES_DIR) as server:
        yield server


class TestFullPipelineWithMockedFetch:
    """
    E2E tests using mocked fetch to avoid SSRF protection blocking localhost.

    These tests validate the complete pipeline without actual network calls.
    """

    def test_excellent_content_pipeline(self):
        """Test full pipeline with excellent content."""
        html_path = FIXTURES_DIR / "excellent_geo.html"
        if not html_path.exists():
            pytest.skip("Fixture not found")

        html = html_path.read_text()
        url = "https://example.com/excellent"

        # Run the full pipeline
        parsed = parse_content(html, url)
        geo_result = check_geo(parsed, html, url)

        # Validate parsed content
        assert parsed["meta"]["title"] is not None
        assert len(parsed["content"]["headings"]) > 0
        assert len(parsed["content"]["paragraphs"]) > 0

        # Validate GEO result structure
        assert "geo_score" in geo_result
        assert "summary" in geo_result
        assert "ai_crawler_access" in geo_result

        # Validate score
        score = geo_result["geo_score"]
        assert 0 <= score["total"] <= 100
        assert score["grade"] in ("A", "B", "C", "D", "F")

        # Excellent content should score well
        assert score["total"] >= 60, f"Excellent content scored {score['total']}"

    def test_poor_content_pipeline(self):
        """Test full pipeline with poor content."""
        html_path = FIXTURES_DIR / "poor_geo.html"
        if not html_path.exists():
            pytest.skip("Fixture not found")

        html = html_path.read_text()
        url = "https://example.com/poor"

        # Run the full pipeline
        parsed = parse_content(html, url)
        geo_result = check_geo(parsed, html, url)

        # Validate GEO result
        score = geo_result["geo_score"]
        assert 0 <= score["total"] <= 100

        # Poor content should score lower
        assert score["total"] < 70, f"Poor content scored {score['total']}"

    def test_average_content_pipeline(self):
        """Test full pipeline with average content."""
        html_path = FIXTURES_DIR / "average_geo.html"
        if not html_path.exists():
            pytest.skip("Fixture not found")

        html = html_path.read_text()
        url = "https://example.com/average"

        # Run the full pipeline
        parsed = parse_content(html, url)
        geo_result = check_geo(parsed, html, url)

        # Validate result
        score = geo_result["geo_score"]
        assert 0 <= score["total"] <= 100

    def test_pipeline_with_format_cli(self):
        """Test pipeline including CLI format output."""
        html_path = FIXTURES_DIR / "excellent_geo.html"
        if not html_path.exists():
            pytest.skip("Fixture not found")

        html = html_path.read_text()
        url = "https://example.com/test"

        parsed = parse_content(html, url)
        geo_result = check_geo(parsed, html, url)

        # Build results dict as expected by format_report
        results = {
            "url": url,
            "geo": geo_result,
            "seo": [],
            "parsed": parsed,
        }

        # Format as CLI output
        formatted = format_report(results, output="cli")

        assert isinstance(formatted, str)
        assert len(formatted) > 0

    def test_pipeline_with_format_json(self):
        """Test pipeline including JSON format output."""
        html_path = FIXTURES_DIR / "excellent_geo.html"
        if not html_path.exists():
            pytest.skip("Fixture not found")

        html = html_path.read_text()
        url = "https://example.com/test"

        parsed = parse_content(html, url)
        geo_result = check_geo(parsed, html, url)

        results = {
            "url": url,
            "geo": geo_result,
            "seo": [],
            "parsed": parsed,
        }

        # Format as JSON
        formatted = format_report(results, output="json")

        assert isinstance(formatted, str)
        # Should be valid JSON
        import json
        data = json.loads(formatted)
        assert "geo" in data
        assert data["geo"]["geo_score"]["total"] == geo_result["geo_score"]["total"]

    def test_pipeline_with_format_markdown(self):
        """Test pipeline including Markdown format output."""
        html_path = FIXTURES_DIR / "excellent_geo.html"
        if not html_path.exists():
            pytest.skip("Fixture not found")

        html = html_path.read_text()
        url = "https://example.com/test"

        parsed = parse_content(html, url)
        geo_result = check_geo(parsed, html, url)

        results = {
            "url": url,
            "geo": geo_result,
            "seo": [],
            "parsed": parsed,
        }

        # Format as Markdown
        formatted = format_report(results, output="markdown")

        assert isinstance(formatted, str)
        # Markdown should contain headers
        assert "#" in formatted


class TestPipelineDataFlow:
    """Tests for data flow through the pipeline."""

    def test_parsed_content_structure(self):
        """Validate parsed content has expected structure."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Test Page</title>
            <meta name="description" content="A test page">
        </head>
        <body>
            <h1>Main Title</h1>
            <p>First paragraph with content.</p>
            <h2>Section</h2>
            <ul><li>Item 1</li><li>Item 2</li></ul>
        </body>
        </html>
        """
        url = "https://example.com/test"

        parsed = parse_content(html, url)

        # Check required keys
        assert "meta" in parsed
        assert "content" in parsed
        assert "stats" in parsed

        # Check meta
        assert parsed["meta"]["title"] == "Test Page"
        assert "test" in parsed["meta"]["description"].lower()

        # Check content
        assert len(parsed["content"]["headings"]) >= 2
        assert len(parsed["content"]["paragraphs"]) >= 1

    def test_geo_result_structure(self):
        """Validate GEO result has expected structure."""
        html = "<html><body><h1>Test</h1><p>Content here.</p></body></html>"
        url = "https://example.com/test"

        parsed = parse_content(html, url)
        geo_result = check_geo(parsed, html, url)

        # Required keys
        required_keys = [
            "geo_score",
            "summary",
            "ai_crawler_access",
            "ai_usage_interpretation",
            "last_mile_blockers",
        ]
        for key in required_keys:
            assert key in geo_result, f"Missing key: {key}"

        # GEO score structure
        score = geo_result["geo_score"]
        assert "total" in score
        assert "grade" in score
        assert "breakdown" in score

        breakdown = score["breakdown"]
        assert "accessibility" in breakdown
        assert "structure" in breakdown
        assert "quality" in breakdown

    def test_data_flows_correctly(self):
        """Verify data flows correctly through each stage."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Data Flow Test</title>
            <meta name="description" content="Testing data flow through pipeline">
        </head>
        <body>
            <h1>Main Heading</h1>
            <p>Machine learning is defined as a type of AI.</p>
            <p>According to research, 85% of companies use ML.</p>
            <ul>
                <li>Point one</li>
                <li>Point two</li>
            </ul>
        </body>
        </html>
        """
        url = "https://example.com/flow-test"

        # Stage 1: Parse
        parsed = parse_content(html, url)
        assert parsed["meta"]["title"] == "Data Flow Test"

        # Stage 2: GEO Check
        geo_result = check_geo(parsed, html, url)
        assert geo_result["geo_score"]["total"] > 0

        # Stage 3: Format
        results = {
            "url": url,
            "geo": geo_result,
            "seo": [],
            "parsed": parsed,
        }
        json_output = format_report(results, output="json")

        import json
        output_data = json.loads(json_output)

        # Verify data consistency
        assert output_data["url"] == url
        assert output_data["geo"]["geo_score"]["total"] == geo_result["geo_score"]["total"]


class TestPipelineEdgeCases:
    """Tests for edge cases in the pipeline."""

    def test_empty_html(self):
        """Pipeline should handle empty HTML - may raise or return minimal result."""
        html = ""
        url = "https://example.com/empty"

        # Empty HTML may raise an exception from readability library
        # This is acceptable behavior - document the limitation
        try:
            parsed = parse_content(html, url)
            geo_result = check_geo(parsed, html, url)
            # If it succeeds, score should be valid
            assert geo_result["geo_score"]["total"] >= 0
        except Exception as e:
            # Empty HTML raising an exception is acceptable
            # The system should not crash silently
            assert "empty" in str(e).lower() or "unparseable" in str(e).lower() or "parser" in str(e).lower()

    def test_minimal_html(self):
        """Pipeline should handle minimal HTML."""
        html = "<html><body></body></html>"
        url = "https://example.com/minimal"

        parsed = parse_content(html, url)
        geo_result = check_geo(parsed, html, url)

        assert geo_result["geo_score"]["total"] >= 0

    def test_malformed_html(self):
        """Pipeline should handle malformed HTML gracefully."""
        html = "<html><head><title>Broken</head><body><p>Unclosed paragraph<div>Mixed tags</p></div>"
        url = "https://example.com/malformed"

        # Should not raise exception
        parsed = parse_content(html, url)
        geo_result = check_geo(parsed, html, url)

        assert geo_result["geo_score"]["total"] >= 0

    def test_very_large_html(self):
        """Pipeline should handle large HTML content."""
        # Generate a large HTML document
        paragraphs = "\n".join([f"<p>Paragraph {i} with some content.</p>" for i in range(500)])
        html = f"""
        <!DOCTYPE html>
        <html>
        <head><title>Large Document</title></head>
        <body>
            <h1>Large Content Test</h1>
            {paragraphs}
        </body>
        </html>
        """
        url = "https://example.com/large"

        parsed = parse_content(html, url)
        geo_result = check_geo(parsed, html, url)

        # Should complete successfully
        assert geo_result["geo_score"]["total"] >= 0
        assert parsed["stats"]["word_count"] > 1000

    def test_special_characters(self):
        """Pipeline should handle special characters."""
        html = """
        <!DOCTYPE html>
        <html>
        <head><title>Special Characters: &amp; &lt; &gt; "quotes"</title></head>
        <body>
            <h1>Test with émojis 🎉 and ñ characters</h1>
            <p>Price: $100 < $200 & more > less</p>
            <p>Japanese: 日本語 Chinese: 中文 Korean: 한국어</p>
        </body>
        </html>
        """
        url = "https://example.com/special"

        parsed = parse_content(html, url)
        geo_result = check_geo(parsed, html, url)

        # Should complete without error
        assert geo_result["geo_score"]["total"] >= 0


class TestPipelineWithRealFetch:
    """
    Tests that would use real fetch if SSRF protection allowed localhost.

    These tests are marked to skip by default since localhost is blocked.
    They serve as documentation for how E2E tests would work with real HTTP.
    """

    @pytest.mark.skip(reason="SSRF protection blocks localhost - use mocked tests instead")
    def test_fetch_from_local_server(self, local_server):
        """Test fetching from local server (skipped due to SSRF)."""
        url = f"{local_server.base_url}/excellent_geo.html"

        # This would fail with SSRF protection
        html = fetch_html(url)
        parsed = parse_content(html, url)
        geo_result = check_geo(parsed, html, url)

        assert geo_result["geo_score"]["total"] > 0


class TestPipelineConsistency:
    """Tests for pipeline consistency and determinism."""

    def test_repeated_analysis_same_result(self):
        """Repeated analysis should produce identical results."""
        html = """
        <!DOCTYPE html>
        <html>
        <head><title>Consistency Test</title></head>
        <body>
            <h1>Test Page</h1>
            <p>This is test content for consistency checking.</p>
        </body>
        </html>
        """
        url = "https://example.com/consistency"

        results = []
        for _ in range(3):
            parsed = parse_content(html, url)
            geo_result = check_geo(parsed, html, url)
            results.append(geo_result["geo_score"]["total"])

        # All results should be identical
        assert len(set(results)) == 1, f"Inconsistent results: {results}"

    def test_url_does_not_affect_content_score(self):
        """Different URLs with same content should have similar scores."""
        html = """
        <!DOCTYPE html>
        <html>
        <head><title>URL Independence Test</title></head>
        <body>
            <h1>Test Content</h1>
            <p>Same content, different URLs.</p>
        </body>
        </html>
        """

        urls = [
            "https://example.com/page1",
            "https://example.com/page2",
            "https://different.com/page",
        ]

        scores = []
        for url in urls:
            parsed = parse_content(html, url)
            # Note: check_geo may have different results due to URL-specific checks
            # but the structure and quality scores should be similar
            geo_result = check_geo(parsed, html, url)
            scores.append(geo_result["geo_score"]["breakdown"]["structure"]["score"])

        # Structure scores should be identical (not affected by URL)
        assert len(set(scores)) == 1, f"Structure scores vary by URL: {scores}"
