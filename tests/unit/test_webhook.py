"""Tests for webhook alert evaluation and delivery."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
import requests

import src.scheduler.webhook as webhook
from src.db.store import get_conn, init_db, mark_alert_sent, upsert_url


def _seed_url_with_alert(db_path, *, last_alert_at: str = "") -> int:
    conn = get_conn(db_path)
    try:
        init_db(conn)
        url_id = upsert_url(conn, "https://example.com/article")
        if last_alert_at:
            mark_alert_sent(conn, url_id, last_alert_at)
        return url_id
    finally:
        conn.close()


def test_grade_dropped_yes() -> None:
    assert webhook._grade_dropped("B", "C") is True


def test_grade_dropped_no() -> None:
    assert webhook._grade_dropped("B", "A") is False


def test_grade_dropped_same() -> None:
    assert webhook._grade_dropped("B", "B") is False


def test_evaluate_no_triggers(monkeypatch: pytest.MonkeyPatch) -> None:
    send_mock = Mock(return_value=True)
    monkeypatch.setattr(webhook, "_send_webhook", send_mock)
    monkeypatch.setattr(webhook, "_is_debounced", lambda url_id: False)

    sent = webhook.evaluate_and_fire_webhook(
        url="https://example.com/article",
        url_id=1,
        webhook_url="https://hooks.example.com/test",
        alert_threshold=70,
        current_score=80,
        current_grade="B",
        previous_scan={"total_score": 82, "grade": "B"},
    )

    assert sent is False
    send_mock.assert_not_called()


def test_evaluate_score_below_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    send_mock = Mock(return_value=True)
    mark_mock = Mock()
    monkeypatch.setattr(webhook, "_send_webhook", send_mock)
    monkeypatch.setattr(webhook, "_mark_alert_sent", mark_mock)
    monkeypatch.setattr(webhook, "_is_debounced", lambda url_id: False)

    sent = webhook.evaluate_and_fire_webhook(
        url="https://example.com/article",
        url_id=1,
        webhook_url="https://hooks.example.com/test",
        alert_threshold=70,
        current_score=65,
        current_grade="C",
        previous_scan={"total_score": 78, "grade": "B"},
    )

    assert sent is True
    send_mock.assert_called_once()
    mark_mock.assert_called_once_with(1)


def test_evaluate_grade_drop(monkeypatch: pytest.MonkeyPatch) -> None:
    send_mock = Mock(return_value=True)
    mark_mock = Mock()
    monkeypatch.setattr(webhook, "_send_webhook", send_mock)
    monkeypatch.setattr(webhook, "_mark_alert_sent", mark_mock)
    monkeypatch.setattr(webhook, "_is_debounced", lambda url_id: False)

    sent = webhook.evaluate_and_fire_webhook(
        url="https://example.com/article",
        url_id=2,
        webhook_url="https://hooks.example.com/test",
        alert_threshold=0,
        current_score=72,
        current_grade="C",
        previous_scan={"total_score": 82, "grade": "B"},
    )

    assert sent is True
    send_mock.assert_called_once()
    mark_mock.assert_called_once_with(2)


def test_debounce_within_window(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "geo_checker.db"
    url_id = _seed_url_with_alert(
        db_path,
        last_alert_at=(datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    monkeypatch.setattr(webhook, "get_conn", lambda: get_conn(db_path))

    assert webhook._is_debounced(url_id) is True


def test_debounce_after_window(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "geo_checker.db"
    url_id = _seed_url_with_alert(
        db_path,
        last_alert_at=(datetime.now(UTC) - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    monkeypatch.setattr(webhook, "get_conn", lambda: get_conn(db_path))

    assert webhook._is_debounced(url_id) is False


def test_send_webhook_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class Response:
        status_code = 204

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return Response()

    monkeypatch.setattr(webhook.requests, "post", fake_post)

    sent = webhook._send_webhook(
        "https://hooks.example.com/test",
        {"event": "geo_checker_alert", "current_score": 60},
    )

    assert sent is True
    assert captured["url"] == "https://hooks.example.com/test"
    assert captured["kwargs"]["json"]["event"] == "geo_checker_alert"
    assert captured["kwargs"]["timeout"] == webhook.WEBHOOK_TIMEOUT_SECONDS


def test_send_webhook_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_post(*args, **kwargs):
        raise requests.RequestException("network error")

    monkeypatch.setattr(webhook.requests, "post", fail_post)

    assert webhook._send_webhook("https://hooks.example.com/test", {"event": "x"}) is False
