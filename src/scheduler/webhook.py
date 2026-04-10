"""Webhook delivery for scan alerts."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import requests

from src.db.store import get_conn, init_db, mark_alert_sent

WEBHOOK_TIMEOUT_SECONDS = 10
ALERT_DEBOUNCE_HOURS = 24

GRADE_ORDER = ["A", "B", "C", "D", "F"]


def evaluate_and_fire_webhook(
    *,
    url: str,
    url_id: int,
    webhook_url: str,
    alert_threshold: int,
    current_score: int,
    current_grade: str,
    previous_scan: dict | None,
) -> bool:
    """Evaluate alert conditions and deliver the webhook if required."""
    if not webhook_url:
        return False

    triggers: list[dict[str, Any]] = []
    if alert_threshold > 0 and current_score < alert_threshold:
        triggers.append(
            {
                "type": "score_below_threshold",
                "threshold": alert_threshold,
                "current_score": current_score,
            }
        )

    if previous_scan:
        previous_grade = str(previous_scan.get("grade", ""))
        if _grade_dropped(previous_grade, current_grade):
            triggers.append(
                {
                    "type": "grade_dropped",
                    "from_grade": previous_grade,
                    "to_grade": current_grade,
                }
            )

    if not triggers:
        return False
    if _is_debounced(url_id):
        return False

    payload = {
        "event": "geo_checker_alert",
        "url": url,
        "current_score": current_score,
        "current_grade": current_grade,
        "previous_score": int(previous_scan.get("total_score", 0)) if previous_scan else None,
        "previous_grade": str(previous_scan.get("grade", "")) if previous_scan else None,
        "triggers": triggers,
        "triggered_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    sent = _send_webhook(webhook_url, payload)
    if sent:
        _mark_alert_sent(url_id)
    return sent


def _grade_dropped(previous: str, current: str) -> bool:
    """Return True when the current letter grade is worse than the previous one."""
    if not previous or not current:
        return False
    try:
        previous_index = GRADE_ORDER.index(previous.upper())
        current_index = GRADE_ORDER.index(current.upper())
    except ValueError:
        return False
    return current_index > previous_index


def _is_debounced(url_id: int) -> bool:
    """Return True when the URL already alerted within the debounce window."""
    conn = get_conn()
    try:
        init_db(conn)
        row = conn.execute(
            "SELECT last_alert_at FROM urls WHERE id = ?",
            (url_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None or not row["last_alert_at"]:
        return False

    try:
        last_alert = datetime.fromisoformat(str(row["last_alert_at"]).replace("Z", "+00:00"))
    except ValueError:
        return False
    if last_alert.tzinfo is None:
        last_alert = last_alert.replace(tzinfo=UTC)

    return datetime.now(UTC) - last_alert < timedelta(hours=ALERT_DEBOUNCE_HOURS)


def _send_webhook(webhook_url: str, payload: dict[str, Any]) -> bool:
    """Send the webhook request. Failures are returned as False, not raised."""
    try:
        response = requests.post(
            webhook_url,
            json=payload,
            timeout=WEBHOOK_TIMEOUT_SECONDS,
            headers={"User-Agent": "GEO-Checker/4.0 (+https://gc.ranran.tw)"},
        )
    except requests.RequestException:
        return False
    return 200 <= response.status_code < 300


def _mark_alert_sent(url_id: int) -> None:
    """Persist the last successful webhook delivery timestamp."""
    conn = get_conn()
    try:
        init_db(conn)
        mark_alert_sent(conn, url_id, datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    finally:
        conn.close()
