"""Tests for monitoring API endpoints."""
from __future__ import annotations

from unittest.mock import patch
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from app.api.services.auth import api_key_manager
from app.main import app
from src.config.settings import settings
from src.db.store import get_conn, init_db

TEST_API_KEY = "monitoring-test-key"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def reset_rate_limiter():
    from app.api.v1.deps import api_rate_limiter

    api_rate_limiter._requests.clear()
    yield
    api_rate_limiter._requests.clear()


@pytest.fixture
def monitoring_auth(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GEO_API_KEY_MONITORING_TEST", f"{TEST_API_KEY}:premium")
    api_key_manager.reload()
    monkeypatch.setattr(settings.security, "monitoring_require_api_key", True)
    monkeypatch.setattr(settings.security, "webhook_guard_mode", "strict")
    yield
    monkeypatch.delenv("GEO_API_KEY_MONITORING_TEST", raising=False)
    api_key_manager.reload()


@pytest.fixture
def auth_headers(monitoring_auth):
    return {"X-API-Key": TEST_API_KEY}


def test_set_monitoring_basic(
    client: TestClient,
    reset_rate_limiter,
    auth_headers,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "geo_checker.db"
    monkeypatch.setattr("app.api.v1.endpoints.monitoring.get_conn", lambda: get_conn(db_path))
    monkeypatch.setattr(
        "app.api.v1.endpoints.monitoring.validate_webhook_url",
        lambda url: (True, ""),
    )

    payload = {
        "url": "https://example.com/article",
        "rescan_cron": "daily",
        "webhook_url": "https://hooks.example.com/test",
        "alert_threshold": 70,
    }

    response = client.put("/api/v1/monitoring", json=payload, headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["url"] == payload["url"]
    assert data["config"]["rescan_cron"] == "daily"
    assert data["config"]["webhook_url"] == payload["webhook_url"]
    assert data["config"]["alert_threshold"] == 70

    get_response = client.get(
        f"/api/v1/monitoring/{quote(payload['url'], safe='')}",
        headers=auth_headers,
    )
    assert get_response.status_code == 200
    assert get_response.json()["config"]["rescan_cron"] == "daily"

    conn = get_conn(db_path)
    try:
        audit_row = conn.execute(
            """
            SELECT actor_key_name, actor_tier, old_webhook_url, new_webhook_url, action
            FROM monitoring_audit_log
            ORDER BY id DESC
            LIMIT 1
            """,
        ).fetchone()
    finally:
        conn.close()

    assert audit_row is not None
    assert audit_row["actor_key_name"] == "MONITORING_TEST"
    assert audit_row["actor_tier"] == "premium"
    assert audit_row["old_webhook_url"] == ""
    assert audit_row["new_webhook_url"] == payload["webhook_url"]
    assert audit_row["action"] == "update_monitoring"


def test_monitoring_requires_api_key(
    client: TestClient,
    reset_rate_limiter,
    monitoring_auth,
) -> None:
    response = client.post("/api/v1/monitoring/run-now")

    assert response.status_code == 401
    assert response.json()["detail"]["error"]["message"] == "Authentication required."


def test_monitoring_invalid_api_key_rejected(
    client: TestClient,
    reset_rate_limiter,
    monitoring_auth,
) -> None:
    response = client.post(
        "/api/v1/monitoring/run-now",
        headers={"X-API-Key": "invalid-key"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "INVALID_API_KEY"


def test_set_monitoring_invalid_webhook_url(
    client: TestClient,
    reset_rate_limiter,
    auth_headers,
) -> None:
    response = client.put(
        "/api/v1/monitoring",
        json={
            "url": "https://example.com/article",
            "rescan_cron": "daily",
            "webhook_url": "ftp://hooks.example.com/test",
            "alert_threshold": 70,
        },
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error"]["code"] == "INVALID_WEBHOOK_URL"


def test_set_monitoring_invalid_threshold(
    client: TestClient,
    reset_rate_limiter,
    auth_headers,
) -> None:
    response = client.put(
        "/api/v1/monitoring",
        json={
            "url": "https://example.com/article",
            "rescan_cron": "daily",
            "webhook_url": "https://hooks.example.com/test",
            "alert_threshold": 101,
        },
        headers=auth_headers,
    )

    assert response.status_code == 422


def test_get_monitoring_not_found(
    client: TestClient,
    reset_rate_limiter,
    auth_headers,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "geo_checker.db"
    conn = get_conn(db_path)
    init_db(conn)
    conn.close()
    monkeypatch.setattr("app.api.v1.endpoints.monitoring.get_conn", lambda: get_conn(db_path))

    response = client.get(
        f"/api/v1/monitoring/{quote('https://example.com/missing', safe='')}",
        headers=auth_headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"]["error"]["code"] == "URL_NOT_TRACKED"


def test_run_now_returns_count(
    client: TestClient,
    reset_rate_limiter,
    auth_headers,
) -> None:
    with patch("app.api.v1.endpoints.monitoring.run_due_scans", return_value=2):
        response = client.post("/api/v1/monitoring/run-now", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["triggered"] == 2
