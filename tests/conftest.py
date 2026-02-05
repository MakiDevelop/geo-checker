"""Shared test fixtures and configuration."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    """Return path to test fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def valid_html() -> str:
    """Return a valid HTML page for testing."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Test Page - GEO Checker Example</title>
    <meta name="description" content="This is a test page for validating GEO checker functionality. It contains various content elements for comprehensive testing.">
    <link rel="canonical" href="https://example.com/test-page">
    <meta name="robots" content="index, follow">
</head>
<body>
    <h1>Main Heading for Test Page</h1>
    <p>This is the first paragraph with some introductory content about the test page.</p>

    <h2>Section One: Overview</h2>
    <p>Machine learning is defined as a subset of artificial intelligence that enables systems to learn from data.</p>
    <p>According to a 2024 study, 85% of enterprises now use some form of AI technology.</p>

    <h2>Section Two: Details</h2>
    <ul>
        <li>First item in the list</li>
        <li>Second item with more details</li>
        <li>Third item for completeness</li>
    </ul>

    <h3>Subsection: Technical Details</h3>
    <p>The implementation uses Python 3.11 with FastAPI framework.</p>

    <table>
        <tr><th>Feature</th><th>Status</th></tr>
        <tr><td>HTML Parsing</td><td>Complete</td></tr>
        <tr><td>GEO Scoring</td><td>Complete</td></tr>
    </table>

    <img src="/images/test.jpg" alt="Test image description">

    <a href="/internal-link">Internal Link</a>
    <a href="https://external.com">External Link</a>
</body>
</html>"""


@pytest.fixture
def minimal_html() -> str:
    """Return minimal HTML for edge case testing."""
    return """<!DOCTYPE html>
<html>
<head><title>Minimal</title></head>
<body><p>Content</p></body>
</html>"""


@pytest.fixture
def html_missing_meta() -> str:
    """Return HTML with missing meta tags."""
    return """<!DOCTYPE html>
<html>
<head><title>No Description</title></head>
<body>
    <p>Some content without meta description.</p>
</body>
</html>"""


@pytest.fixture
def html_multiple_h1() -> str:
    """Return HTML with multiple H1 tags."""
    return """<!DOCTYPE html>
<html>
<head>
    <title>Multiple H1 Test</title>
    <meta name="description" content="Testing multiple H1 tags">
</head>
<body>
    <h1>First H1</h1>
    <p>Content</p>
    <h1>Second H1</h1>
    <p>More content</p>
</body>
</html>"""


@pytest.fixture
def html_noindex() -> str:
    """Return HTML with noindex directive."""
    return """<!DOCTYPE html>
<html>
<head>
    <title>Noindex Page</title>
    <meta name="robots" content="noindex, nofollow">
</head>
<body>
    <h1>Hidden Page</h1>
    <p>This page should not be indexed.</p>
</body>
</html>"""


@pytest.fixture
def mock_url() -> str:
    """Return a mock URL for testing."""
    return "https://example.com/test-page"


@pytest.fixture
def parsed_content(valid_html: str, mock_url: str) -> dict:
    """Return parsed content from valid HTML."""
    from src.parser.content_parser import parse_content
    return parse_content(valid_html, mock_url)


@pytest.fixture
def robots_txt_allow_all() -> str:
    """Return robots.txt that allows all crawlers."""
    return """User-agent: *
Allow: /

User-agent: GPTBot
Allow: /

User-agent: ClaudeBot
Allow: /
"""


@pytest.fixture
def robots_txt_block_ai() -> str:
    """Return robots.txt that blocks AI crawlers."""
    return """User-agent: *
Allow: /

User-agent: GPTBot
Disallow: /

User-agent: ClaudeBot
Disallow: /

User-agent: PerplexityBot
Disallow: /
"""
