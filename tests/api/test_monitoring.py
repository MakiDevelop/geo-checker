"""Tests for monitoring API endpoints."""
from __future__ import annotations

import sys
import types
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

from app.main import app
from src.db.store import get_conn, init_db


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def reset_rate_limiter():
    from app.api.v1.deps import api_rate_limiter

    api_rate_limiter._requests.clear()
    yield
    api_rate_limiter._requests.clear()


def test_set_monitoring_basic(
    client: TestClient,
    reset_rate_limiter,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "geo_checker.db"
    monkeypatch.setattr("app.api.v1.endpoints.monitoring.get_conn", lambda: get_conn(db_path))

    payload = {
        "url": "https://example.com/article",
        "rescan_cron": "daily",
        "webhook_url": "https://hooks.example.com/test",
        "alert_threshold": 70,
    }

    response = client.put("/api/v1/monitoring", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["url"] == payload["url"]
    assert data["config"]["rescan_cron"] == "daily"
    assert data["config"]["webhook_url"] == payload["webhook_url"]
    assert data["config"]["alert_threshold"] == 70

    get_response = client.get(f"/api/v1/monitoring/{quote(payload['url'], safe='')}")
    assert get_response.status_code == 200
    assert get_response.json()["config"]["rescan_cron"] == "daily"


def test_set_monitoring_invalid_webhook_url(
    client: TestClient,
    reset_rate_limiter,
) -> None:
    response = client.put(
        "/api/v1/monitoring",
        json={
            "url": "https://example.com/article",
            "rescan_cron": "daily",
            "webhook_url": "ftp://hooks.example.com/test",
            "alert_threshold": 70,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error"]["code"] == "INVALID_WEBHOOK_URL"


def test_set_monitoring_invalid_threshold(
    client: TestClient,
    reset_rate_limiter,
) -> None:
    response = client.put(
        "/api/v1/monitoring",
        json={
            "url": "https://example.com/article",
            "rescan_cron": "daily",
            "webhook_url": "https://hooks.example.com/test",
            "alert_threshold": 101,
        },
    )

    assert response.status_code == 422


def test_get_monitoring_not_found(
    client: TestClient,
    reset_rate_limiter,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "geo_checker.db"
    conn = get_conn(db_path)
    init_db(conn)
    conn.close()
    monkeypatch.setattr("app.api.v1.endpoints.monitoring.get_conn", lambda: get_conn(db_path))

    response = client.get(f"/api/v1/monitoring/{quote('https://example.com/missing', safe='')}")

    assert response.status_code == 404
    assert response.json()["detail"]["error"]["code"] == "URL_NOT_TRACKED"


def test_run_now_returns_count(
    client: TestClient,
    reset_rate_limiter,
) -> None:
    with patch("app.api.v1.endpoints.monitoring.run_due_scans", return_value=2):
        response = client.post("/api/v1/monitoring/run-now")

    assert response.status_code == 200
    assert response.json()["triggered"] == 2
