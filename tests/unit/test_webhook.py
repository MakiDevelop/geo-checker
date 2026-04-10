"""Tests for webhook alert evaluation and delivery."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from urllib3.exceptions import HTTPError

import src.scheduler.webhook as webhook
from src.config.settings import settings
from src.db.store import get_conn, init_db, mark_alert_sent, upsert_url
from src.security.url_guard import ResolvedWebhookTarget, WebhookValidationError


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

    target = ResolvedWebhookTarget(
        original_url="https://hooks.example.com/test",
        scheme="https",
        hostname="hooks.example.com",
        host_header="hooks.example.com",
        port=443,
        path_and_query="/test",
        resolved_ips=("8.8.8.8",),
        pinned_ip="8.8.8.8",
    )

    class Response:
        status = 204

        def drain_conn(self):
            return None

        def release_conn(self):
            return None

    class FakePool:
        def __init__(self, **kwargs):
            captured["pool_init"] = kwargs

        def urlopen(self, method, url, **kwargs):
            captured["method"] = method
            captured["url"] = url
            captured["kwargs"] = kwargs
            return Response()

        def close(self):
            captured["closed"] = True

    monkeypatch.setattr(settings.security, "webhook_guard_mode", "strict")
    monkeypatch.setattr(webhook, "resolve_webhook_target", lambda *_args, **_kwargs: target)
    monkeypatch.setattr(webhook, "HTTPSConnectionPool", FakePool)

    sent = webhook._send_webhook(
        "https://hooks.example.com/test",
        {"event": "geo_checker_alert", "current_score": 60},
    )

    assert sent is True
    assert captured["method"] == "POST"
    assert captured["url"] == "/test"
    assert json.loads(captured["kwargs"]["body"].decode("utf-8"))["event"] == "geo_checker_alert"
    assert captured["kwargs"]["redirect"] is False
    assert captured["kwargs"]["headers"]["Host"] == "hooks.example.com"
    assert captured["pool_init"]["host"] == "8.8.8.8"
    assert captured["pool_init"]["server_hostname"] == "hooks.example.com"
    assert captured["closed"] is True


def test_send_webhook_redirect_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    target = ResolvedWebhookTarget(
        original_url="https://hooks.example.com/test",
        scheme="https",
        hostname="hooks.example.com",
        host_header="hooks.example.com",
        port=443,
        path_and_query="/test",
        resolved_ips=("8.8.8.8",),
        pinned_ip="8.8.8.8",
    )

    class Response:
        status = 302

        def drain_conn(self):
            return None

        def release_conn(self):
            return None

    class FakePool:
        def __init__(self, **kwargs):
            pass

        def urlopen(self, method, url, **kwargs):
            return Response()

        def close(self):
            return None

    monkeypatch.setattr(settings.security, "webhook_guard_mode", "strict")
    monkeypatch.setattr(webhook, "resolve_webhook_target", lambda *_args, **_kwargs: target)
    monkeypatch.setattr(webhook, "HTTPSConnectionPool", FakePool)

    assert webhook._send_webhook("https://hooks.example.com/test", {"event": "x"}) is False


def test_send_webhook_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    target = ResolvedWebhookTarget(
        original_url="https://hooks.example.com/test",
        scheme="https",
        hostname="hooks.example.com",
        host_header="hooks.example.com",
        port=443,
        path_and_query="/test",
        resolved_ips=("8.8.8.8",),
        pinned_ip="8.8.8.8",
    )

    class FakePool:
        def __init__(self, **kwargs):
            pass

        def urlopen(self, method, url, **kwargs):
            raise HTTPError("network error")

        def close(self):
            return None

    monkeypatch.setattr(settings.security, "webhook_guard_mode", "strict")
    monkeypatch.setattr(webhook, "resolve_webhook_target", lambda *_args, **_kwargs: target)
    monkeypatch.setattr(webhook, "HTTPSConnectionPool", FakePool)

    assert webhook._send_webhook("https://hooks.example.com/test", {"event": "x"}) is False


def test_send_webhook_invalid_target_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings.security, "webhook_guard_mode", "strict")
    monkeypatch.setattr(
        webhook,
        "resolve_webhook_target",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(WebhookValidationError("blocked")),
    )

    assert webhook._send_webhook("https://hooks.example.com/test", {"event": "x"}) is False
