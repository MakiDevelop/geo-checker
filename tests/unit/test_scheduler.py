"""Tests for periodic rescan scheduling."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import src.scheduler.rescan_scheduler as scheduler
from src.db.store import get_conn, get_due_rescans, init_db, update_url_monitoring, upsert_url


def _iso_now_minus(*, hours: int = 0, days: int = 0) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours, days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed_monitored_url(
    db_path,
    *,
    url: str,
    rescan_cron: str,
    last_scanned_at: str = "",
    webhook_url: str = "",
    alert_threshold: int = 0,
) -> int:
    conn = get_conn(db_path)
    try:
        init_db(conn)
        url_id = upsert_url(conn, url)
        update_url_monitoring(
            conn,
            url,
            rescan_cron=rescan_cron,
            webhook_url=webhook_url,
            alert_threshold=alert_threshold,
        )
        if last_scanned_at:
            conn.execute(
                "UPDATE urls SET last_scanned_at = ? WHERE id = ?",
                (last_scanned_at, url_id),
            )
            conn.commit()
        return url_id
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def clear_stop_event() -> None:
    scheduler._stop_event.clear()
    yield
    scheduler._stop_event.clear()


def test_is_enabled_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEO_CHECKER_ENABLE_SCHEDULER", raising=False)
    assert scheduler.is_enabled() is False

    monkeypatch.setenv("GEO_CHECKER_ENABLE_SCHEDULER", "1")
    assert scheduler.is_enabled() is True


def test_run_due_scans_empty(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "geo_checker.db"
    monkeypatch.setattr(scheduler, "get_conn", lambda: get_conn(db_path))

    assert scheduler.run_due_scans() == 0


def test_run_due_scans_with_due_url(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "geo_checker.db"
    url = "https://example.com/monitored"
    _seed_monitored_url(
        db_path,
        url=url,
        rescan_cron="hourly",
        last_scanned_at=_iso_now_minus(hours=2),
    )

    save_scan_mock = Mock(return_value=1)
    monkeypatch.setattr(scheduler, "get_conn", lambda: get_conn(db_path))
    monkeypatch.setattr(
        scheduler,
        "fetch_html",
        lambda target: SimpleNamespace(html="<html></html>", final_url=target),
    )
    monkeypatch.setattr(
        scheduler,
        "parse_content",
        lambda html, target: {
            "url": target,
            "stats": {"word_count": 320},
            "readability": {},
            "schema_org": {},
        },
    )
    monkeypatch.setattr(
        scheduler,
        "check_geo",
        lambda parsed, html, target, fetch_result=None: {
            "geo_score": {"total": 74, "grade": "B", "grade_label": "Good"},
        },
    )
    monkeypatch.setattr(scheduler, "save_scan", save_scan_mock)

    assert scheduler.run_due_scans() == 1
    save_scan_mock.assert_called_once()


def test_get_due_rescans_hourly(tmp_path) -> None:
    db_path = tmp_path / "geo_checker.db"
    url = "https://example.com/hourly"
    _seed_monitored_url(
        db_path,
        url=url,
        rescan_cron="hourly",
        last_scanned_at=_iso_now_minus(hours=2),
    )

    conn = get_conn(db_path)
    try:
        init_db(conn)
        due = get_due_rescans(conn)
    finally:
        conn.close()

    assert [item["url"] for item in due] == [url]


def test_get_due_rescans_never_scanned(tmp_path) -> None:
    db_path = tmp_path / "geo_checker.db"
    url = "https://example.com/never"
    _seed_monitored_url(db_path, url=url, rescan_cron="daily")

    conn = get_conn(db_path)
    try:
        init_db(conn)
        due = get_due_rescans(conn)
    finally:
        conn.close()

    assert due[0]["url"] == url
    assert due[0]["last_scanned_at"] == ""


def test_get_due_rescans_not_due(tmp_path) -> None:
    db_path = tmp_path / "geo_checker.db"
    url = "https://example.com/not-due"
    _seed_monitored_url(
        db_path,
        url=url,
        rescan_cron="daily",
        last_scanned_at=_iso_now_minus(hours=1),
    )

    conn = get_conn(db_path)
    try:
        init_db(conn)
        due = get_due_rescans(conn)
    finally:
        conn.close()

    assert due == []
