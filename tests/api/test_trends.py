"""Tests for trend tracking and fix endpoints."""
from __future__ import annotations

import sys
import types
from copy import deepcopy
from datetime import UTC, datetime
from unittest.mock import patch
from urllib.parse import quote

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

from app.api.services.job_queue import Job
from app.main import app
from src.db.store import get_conn, init_db, save_scan, upsert_url


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def reset_rate_limiter():
    """Reset API rate limiter between tests."""
    from app.api.v1.deps import api_rate_limiter

    api_rate_limiter._requests.clear()
    yield
    api_rate_limiter._requests.clear()


def _sample_result() -> dict:
    return {
        "geo": {
            "geo_score": {
                "total": 68,
                "grade": "C",
                "grade_label": "Fair",
                "breakdown": {
                    "accessibility": {"score": 18, "max": 40, "percentage": 45},
                    "structure": {"score": 25, "max": 30, "percentage": 83},
                    "quality": {"score": 25, "max": 30, "percentage": 83},
                },
            },
            "summary": {
                "issues": {
                    "critical": [{"key": "crawlers_blocked", "crawlers": ["GPTBot"]}],
                    "warning": [{"key": "no_schema"}],
                    "good": [],
                },
                "priority_fixes": [],
            },
            "ai_crawler_access": {
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
            },
        },
        "draft_mode": False,
        "parsed_snapshot": {
            "url": "https://example.com/article",
            "meta": {"title": "Example", "description": ""},
            "content": {
                "headings": [{"level": "h1", "text": "Example", "paragraphs": []}],
                "paragraphs": ["Example paragraph about GEO visibility."],
            },
            "stats": {"word_count": 220},
            "schema_org": {"available": False, "types_found": []},
            "freshness": {"has_dates": False},
            "author_info": {"has_author": False},
        },
    }


def test_trends_history_and_diff(client, reset_rate_limiter, tmp_path) -> None:
    """Historical trend and diff endpoints should read persisted scans."""
    db_path = tmp_path / "geo_checker.db"
    conn = get_conn(db_path)
    init_db(conn)

    url = "https://example.com/article"
    url_id = upsert_url(conn, url)
    scan_a = save_scan(conn, url_id, _sample_result())

    improved = deepcopy(_sample_result())
    improved["geo"]["geo_score"]["total"] = 80
    improved["geo"]["geo_score"]["grade"] = "B"
    improved["geo"]["geo_score"]["grade_label"] = "Good"
    improved["geo"]["geo_score"]["breakdown"]["accessibility"]["score"] = 30
    improved["geo"]["geo_score"]["breakdown"]["accessibility"]["percentage"] = 75
    improved["geo"]["summary"]["issues"]["critical"] = []
    improved["geo"]["summary"]["issues"]["warning"] = [{"key": "no_author"}]
    improved["geo"]["ai_crawler_access"]["crawlers"]["gptbot"]["status"] = "allow"
    scan_b = save_scan(conn, url_id, improved)
    conn.close()

    with patch("app.api.v1.endpoints.trends.get_conn", side_effect=lambda: get_conn(db_path)):
        history_response = client.get(f"/api/v1/trends/{quote(url, safe='')}")
        diff_response = client.get(
            "/api/v1/trends/diff",
            params={"scan_a": scan_a, "scan_b": scan_b},
        )

    assert history_response.status_code == 200
    history_data = history_response.json()
    assert history_data["url"] == url
    assert history_data["history"][0]["scan_id"] == scan_b

    assert diff_response.status_code == 200
    diff_data = diff_response.json()
    assert diff_data["score_delta"] == 12
    assert diff_data["crawler_changes"][0]["from"] == "disallow"
    assert diff_data["crawler_changes"][0]["to"] == "allow"


def test_fixes_endpoint_returns_fix_snippets(client, reset_rate_limiter) -> None:
    """Completed jobs should expose copy-pasteable fixes."""
    job_id = "e" * 32
    result = _sample_result()
    result["geo"]["ai_crawler_access"]["meta_robots"] = {
        "content": "noindex, nofollow",
        "noindex": True,
        "nofollow": True,
    }

    job = Job(
        id=job_id,
        url="https://example.com/article",
        status="completed",
        created_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        result=result,
        error=None,
    )

    with patch("app.api.v1.endpoints.trends.job_queue.get", return_value=job):
        response = client.get(f"/api/v1/fixes/{job_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == job_id
    assert any(item["title"] == "Allow blocked AI crawlers in robots.txt" for item in data["fixes"])
    assert any(item["title"] == "Remove noindex directives" for item in data["fixes"])
