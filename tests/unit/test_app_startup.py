"""Tests for startup webhook sanitization."""
from __future__ import annotations

import pytest

from app.main import sanitize_existing_webhooks
from src.config.settings import settings
from src.db.store import get_conn, init_db, update_url_monitoring, upsert_url


def _seed_url_with_webhook(db_path, *, url: str, webhook_url: str) -> None:
    conn = get_conn(db_path)
    try:
        init_db(conn)
        upsert_url(conn, url)
        update_url_monitoring(conn, url, webhook_url=webhook_url)
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def strict_guard_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings.security, "webhook_guard_mode", "strict")


def test_sanitize_existing_webhooks_keeps_valid_webhook(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "geo_checker.db"
    url = "https://example.com/article"
    webhook_url = "https://hooks.example.com/test"
    _seed_url_with_webhook(db_path, url=url, webhook_url=webhook_url)

    monkeypatch.setattr("app.main.get_conn", lambda: get_conn(db_path))
    monkeypatch.setattr(
        "app.main.validate_webhook_url",
        lambda value: (True, "") if value == webhook_url else (False, "unexpected"),
    )

    sanitized = sanitize_existing_webhooks()

    conn = get_conn(db_path)
    try:
        row = conn.execute("SELECT webhook_url FROM urls WHERE url = ?", (url,)).fetchone()
        audit_count = conn.execute("SELECT COUNT(*) AS count FROM monitoring_audit_log").fetchone()
    finally:
        conn.close()

    assert sanitized == 0
    assert row is not None
    assert row["webhook_url"] == webhook_url
    assert int(audit_count["count"]) == 0


def test_sanitize_existing_webhooks_clears_invalid_webhook_and_audits(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "geo_checker.db"
    url = "https://example.com/article"
    webhook_url = "https://hooks.example.com/test"
    _seed_url_with_webhook(db_path, url=url, webhook_url=webhook_url)

    monkeypatch.setattr("app.main.get_conn", lambda: get_conn(db_path))
    monkeypatch.setattr(
        "app.main.validate_webhook_url",
        lambda value: (False, "blocked internal target"),
    )

    sanitized = sanitize_existing_webhooks()

    conn = get_conn(db_path)
    try:
        row = conn.execute("SELECT webhook_url FROM urls WHERE url = ?", (url,)).fetchone()
        audit_row = conn.execute(
            """
            SELECT actor_key_name, actor_tier, action, old_webhook_url, new_webhook_url, reason
            FROM monitoring_audit_log
            ORDER BY id DESC
            LIMIT 1
            """,
        ).fetchone()
    finally:
        conn.close()

    assert sanitized == 1
    assert row is not None
    assert row["webhook_url"] == ""
    assert audit_row is not None
    assert audit_row["actor_key_name"] == "system/backfill"
    assert audit_row["actor_tier"] == "system/backfill"
    assert audit_row["action"] == "sanitize_invalid_webhook"
    assert audit_row["old_webhook_url"] == webhook_url
    assert audit_row["new_webhook_url"] == ""
    assert audit_row["reason"] == "blocked internal target"


def test_sanitize_existing_webhooks_skips_empty_webhook(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "geo_checker.db"
    url = "https://example.com/article"
    _seed_url_with_webhook(db_path, url=url, webhook_url="")

    monkeypatch.setattr("app.main.get_conn", lambda: get_conn(db_path))

    calls = {"count": 0}

    def fake_validate(_value: str):
        calls["count"] += 1
        return False, "should not run"

    monkeypatch.setattr("app.main.validate_webhook_url", fake_validate)

    sanitized = sanitize_existing_webhooks()

    conn = get_conn(db_path)
    try:
        audit_count = conn.execute("SELECT COUNT(*) AS count FROM monitoring_audit_log").fetchone()
    finally:
        conn.close()

    assert sanitized == 0
    assert calls["count"] == 0
    assert int(audit_count["count"]) == 0
