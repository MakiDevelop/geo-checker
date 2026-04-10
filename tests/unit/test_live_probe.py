"""Tests for the live Perplexity probe helper."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.ai.live_probe import (
    _extract_domain,
    generate_probe_queries,
    probe_perplexity,
)


def test_generate_probe_queries_from_title() -> None:
    parsed = {
        "meta": {"title": "Example GEO Page"},
        "content": {"headings": []},
        "entities": [],
    }

    assert generate_probe_queries(parsed, limit=3) == ["What is Example GEO Page?"]


def test_generate_probe_queries_from_headings() -> None:
    parsed = {
        "meta": {"title": ""},
        "content": {
            "headings": [
                {"level": "h1", "text": "Overview"},
                {"level": "h2", "text": "How GEO works?"},
                {"level": "h3", "text": "Ignored subsection"},
            ]
        },
        "entities": [],
    }

    assert generate_probe_queries(parsed, limit=3) == [
        "What is Overview?",
        "How GEO works?",
    ]


def test_generate_probe_queries_limit() -> None:
    parsed = {
        "meta": {"title": "Main Topic"},
        "content": {
            "headings": [
                {"level": "h1", "text": "Subtopic One"},
                {"level": "h2", "text": "Subtopic Two"},
            ]
        },
        "entities": [
            {"text": "Perplexity", "label": "ORG"},
            {"text": "Taipei", "label": "GPE"},
        ],
    }

    queries = generate_probe_queries(parsed, limit=3)

    assert len(queries) == 3


def test_generate_probe_queries_dedupe() -> None:
    parsed = {
        "meta": {"title": "Overview"},
        "content": {
            "headings": [
                {"level": "h1", "text": "Overview"},
                {"level": "h2", "text": "overview"},
            ]
        },
        "entities": [],
    }

    assert generate_probe_queries(parsed, limit=3) == ["What is Overview?"]


def test_probe_perplexity_success() -> None:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "choices": [{"message": {"content": "Example answer"}}],
        "citations": [{"url": "https://docs.example.com", "title": "Docs"}],
    }

    with patch("src.ai.live_probe.requests.post", return_value=response) as mock_post:
        result = probe_perplexity(
            "https://target.example.com/article",
            ["What is GEO?"],
            "pplx-test-key",
        )

    assert result.error == ""
    assert result.total_queries == 1
    assert result.queries[0].answer == "Example answer"
    assert result.queries[0].citations == [
        {"url": "https://docs.example.com", "title": "Docs", "snippet": ""}
    ]
    assert mock_post.call_args.kwargs["json"]["model"] == "sonar"
    assert mock_post.call_args.kwargs["json"]["return_citations"] is True


def test_probe_perplexity_cites_target() -> None:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "choices": [{"message": {"content": "Answer with citation"}}],
        "citations": [
            {
                "url": "https://www.example.com/source",
                "title": "Example Source",
                "snippet": "Matched snippet",
            }
        ],
    }

    with patch("src.ai.live_probe.requests.post", return_value=response):
        result = probe_perplexity("https://example.com/article", ["What is GEO?"], "pplx-test")

    assert result.cited_count == 1
    assert result.citation_rate == 1.0
    assert result.queries[0].cited_target is True
    assert result.queries[0].cited_snippet == "Matched snippet"


def test_probe_perplexity_no_citation() -> None:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "choices": [{"message": {"content": "Answer without target"}}],
        "citations": ["https://other.example.org/page"],
    }

    with patch("src.ai.live_probe.requests.post", return_value=response):
        result = probe_perplexity("https://example.com/article", ["What is GEO?"], "pplx-test")

    assert result.cited_count == 0
    assert result.queries[0].cited_target is False


def test_probe_perplexity_401() -> None:
    response = MagicMock()
    response.status_code = 401

    with patch("src.ai.live_probe.requests.post", return_value=response):
        result = probe_perplexity("https://example.com/article", ["What is GEO?"], "pplx-test")

    assert result.error == "Invalid API key"


def test_probe_perplexity_429() -> None:
    response = MagicMock()
    response.status_code = 429

    with patch("src.ai.live_probe.requests.post", return_value=response):
        result = probe_perplexity("https://example.com/article", ["What is GEO?"], "pplx-test")

    assert result.error == "Rate limited by Perplexity"


def test_extract_domain() -> None:
    assert _extract_domain("https://www.example.com:8443/path") == "example.com"
    assert _extract_domain("https://blog.example.com/page") == "blog.example.com"
    assert _extract_domain("not-a-url") == ""
