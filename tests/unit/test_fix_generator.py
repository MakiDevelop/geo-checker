"""Tests for copy-pasteable fix generation."""
from __future__ import annotations

from src.toolkit.fix_generator import generate_fixes


def test_generate_fixes_returns_expected_snippets() -> None:
    """Blocked crawlers, noindex, and missing metadata should emit fixes."""
    geo_result = {
        "ai_crawler_access": {
            "crawlers": {
                "gptbot": {
                    "status": "disallow",
                    "display": "GPTBot",
                    "vendor": "OpenAI",
                    "purpose": "both",
                },
                "claudebot": {
                    "status": "disallow",
                    "display": "ClaudeBot",
                    "vendor": "Anthropic",
                    "purpose": "both",
                },
            },
            "meta_robots": {
                "content": "noindex, nofollow",
                "noindex": True,
                "nofollow": True,
            },
            "x_robots_tag": {"value": "", "noindex": False, "nofollow": False},
        }
    }
    parsed = {
        "url": "https://example.com/guide",
        "meta": {"title": "Example Guide", "description": ""},
        "content": {
            "headings": [{"level": "h1", "text": "What is GEO?", "paragraphs": []}],
            "paragraphs": [
                (
                    "Generative Engine Optimization helps AI systems understand "
                    "and cite a page correctly."
                )
            ],
        },
        "stats": {"word_count": 420},
        "schema_org": {"available": False, "types_found": []},
        "freshness": {"has_dates": False},
        "author_info": {"has_author": False},
    }

    fixes = generate_fixes(geo_result, parsed, url=parsed["url"])

    titles = [item.title for item in fixes]
    assert "Allow blocked AI crawlers in robots.txt" in titles
    assert "Remove noindex directives" in titles
    assert "Add Schema.org JSON-LD" in titles
    assert "Add author metadata" in titles
    assert "Add publication date metadata" in titles
    assert "Add a descriptive meta description" in titles
    assert "Ensure nginx does not block AI crawler user agents" in titles

    assert fixes[0].priority == "critical"
    assert "User-agent: GPTBot" in fixes[0].code_snippet
    assert any(
        item.code_snippet == '<meta name="robots" content="index, follow">'
        for item in fixes
    )
    assert any("<script type=\"application/ld+json\">" in item.code_snippet for item in fixes)
    assert any(item.file_hint == "nginx.conf" for item in fixes)
