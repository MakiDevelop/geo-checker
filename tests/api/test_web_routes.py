"""Tests for server-rendered web routes."""
from __future__ import annotations

import json
import sys
import types
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

if "cachetools" not in sys.modules:
    cachetools = types.ModuleType("cachetools")

    class TTLCache(dict):
        def __init__(self, *args, **kwargs):
            super().__init__()

    cachetools.TTLCache = TTLCache
    sys.modules["cachetools"] = cachetools

if "readability" not in sys.modules:
    readability = types.ModuleType("readability")

    class Document:
        def __init__(self, html: str):
            self.html = html

        def summary(self, html_partial: bool = True) -> str:
            return self.html

    readability.Document = Document
    sys.modules["readability"] = readability

if "playwright.sync_api" not in sys.modules:
    playwright = types.ModuleType("playwright")
    sync_api = types.ModuleType("playwright.sync_api")

    class PlaywrightTimeoutError(Exception):
        pass

    def sync_playwright():
        raise RuntimeError("playwright is not available in test environment")

    sync_api.TimeoutError = PlaywrightTimeoutError
    sync_api.sync_playwright = sync_playwright
    playwright.sync_api = sync_api
    sys.modules["playwright"] = playwright
    sys.modules["playwright.sync_api"] = sync_api

from app.main import app
from app.routes import analysis as analysis_routes
from src.db.store import get_conn, init_db, save_scan, upsert_url


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _sample_ui_result(url: str, *, score: int = 68, grade: str = "C") -> dict:
    return {
        "url": url,
        "meta": {
            "title": "Example GEO Page",
            "description": "",
            "canonical": url,
        },
        "content": {
            "paragraphs": ["Example paragraph about GEO visibility and content clarity."],
            "headings": [{"level": "h1", "text": "Example GEO Page"}],
            "lists": [],
            "tables": [],
        },
        "stats": {
            "paragraph_count": 1,
            "heading_count": 1,
            "internal_links": 1,
            "external_links": 0,
            "word_count": 220,
        },
        "content_surface_size": {
            "score": 7,
            "components": {
                "heading_blocks": 1,
                "paragraph_blocks": 1,
                "list_blocks": 0,
                "table_blocks": 0,
            },
        },
        "schema_org": {
            "available": False,
            "types_found": [],
            "types": [],
            "has_faq": False,
            "has_howto": False,
            "has_article": False,
        },
        "readability": {"available": False},
        "quotable_sentences": [],
        "freshness": {"has_dates": False},
        "author_info": {"has_author": False},
        "geo": {
            "geo_score": {
                "total": score,
                "grade": grade,
                "grade_label": "Good" if grade in {"A", "B"} else "Needs Work",
                "breakdown": {
                    "accessibility": {"score": 18, "max": 40, "percentage": 45},
                    "structure": {"score": 25, "max": 30, "percentage": 83},
                    "quality": {"score": 25, "max": 30, "percentage": 83},
                },
            },
            "summary": {
                "summary_key": "good",
                "issues": {
                    "critical": [{"key": "crawlers_blocked"}],
                    "warning": [{"key": "no_schema"}],
                    "good": [],
                },
                "priority_fixes": [],
            },
            "ai_crawler_access": {
                "robots_txt_found": True,
                "crawlers": {
                    "gptbot": {
                        "status": "disallow",
                        "display": "GPTBot",
                        "vendor": "OpenAI",
                        "purpose": "both",
                    }
                },
                "meta_robots": {"content": "", "noindex": False, "nofollow": False},
                "x_robots_tag": {"value": "", "noindex": False, "nofollow": False},
                "notes": "",
            },
            "ai_usage_interpretation": {"type": "Mixed Usage"},
            "interpretation_rule_hints": {},
            "last_mile_blockers": [],
            "structural_fixes": [],
            "extended_metrics": {},
        },
        "draft_mode": False,
    }


def _write_result_file(results_dir: Path, result_id: str, payload: dict) -> None:
    payload = deepcopy(payload)
    payload["analysis_id"] = result_id
    payload["created_at"] = datetime.now(UTC).isoformat()
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / f"{result_id}.json").write_text(json.dumps(payload))


def test_results_page_renders_trend_and_fix_snippets(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    url = "https://example.com/article"
    db_path = tmp_path / "geo_checker.db"
    results_dir = tmp_path / "results"
    result_id = "a" * 32

    baseline = _sample_ui_result(url, score=68, grade="C")
    improved = _sample_ui_result(url, score=80, grade="B")
    _write_result_file(results_dir, result_id, improved)

    conn = get_conn(db_path)
    init_db(conn)
    url_id = upsert_url(conn, url)
    save_scan(conn, url_id, baseline)
    save_scan(conn, url_id, improved)
    conn.close()

    monkeypatch.setattr(analysis_routes, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(analysis_routes, "get_conn", lambda: get_conn(db_path))

    response = client.get(f"/results/{result_id}")

    assert response.status_code == 200
    assert 'id="trend-chart"' in response.text
    assert "Score Trend" in response.text
    assert "Fix Snippets" in response.text
    assert "Allow blocked AI crawlers in robots.txt" in response.text
    assert "Add Schema.org JSON-LD" in response.text


def test_history_page_uses_sqlite_records(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    url = "https://example.com/history"
    db_path = tmp_path / "geo_checker.db"
    results_dir = tmp_path / "results"
    result_id = "b" * 32

    record = _sample_ui_result(url, score=74, grade="B")
    _write_result_file(results_dir, result_id, record)

    conn = get_conn(db_path)
    init_db(conn)
    url_id = upsert_url(conn, url)
    save_scan(conn, url_id, record)
    conn.close()

    monkeypatch.setattr(analysis_routes, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(analysis_routes, "get_conn", lambda: get_conn(db_path))

    response = client.get("/history")

    assert response.status_code == 200
    assert "Last 20 analysis records" in response.text
    assert url in response.text
    assert "history-sparkline" in response.text
    assert f"/results/{result_id}" in response.text


def test_history_page_falls_back_to_json_results(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "geo_checker.db"
    results_dir = tmp_path / "results"
    result_id = "c" * 32
    url = "https://example.com/json-only"

    _write_result_file(results_dir, result_id, _sample_ui_result(url, score=61, grade="C"))

    monkeypatch.setattr(analysis_routes, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(analysis_routes, "get_conn", lambda: get_conn(db_path))

    response = client.get("/history")

    assert response.status_code == 200
    assert "Recent scans loaded from JSON result files" in response.text
    assert url in response.text
    assert f"/results/{result_id}" in response.text
