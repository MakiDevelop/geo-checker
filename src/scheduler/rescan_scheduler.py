"""Background scheduler for periodic URL rescans."""
from __future__ import annotations

import os
import threading
from datetime import UTC, datetime

from src.db.store import (
    get_conn,
    get_due_rescans,
    get_url_history,
    init_db,
    mark_scan_completed,
    save_scan,
    upsert_url,
)
from src.fetcher.html_fetcher import fetch_html
from src.geo.geo_checker import check_geo
from src.parser.content_parser import parse_content
from src.scheduler.webhook import evaluate_and_fire_webhook

CHECK_INTERVAL_SECONDS = 300

_scheduler_thread: threading.Thread | None = None
_stop_event = threading.Event()


def is_enabled() -> bool:
    """Return whether the background scheduler is enabled."""
    return os.environ.get("GEO_CHECKER_ENABLE_SCHEDULER", "").strip() == "1"


def start_scheduler() -> None:
    """Start the background scheduler thread (idempotent)."""
    global _scheduler_thread
    if not is_enabled():
        return
    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        return

    _stop_event.clear()
    _scheduler_thread = threading.Thread(
        target=_scheduler_loop,
        daemon=True,
        name="geo-rescan-scheduler",
    )
    _scheduler_thread.start()


def stop_scheduler() -> None:
    """Signal the scheduler to stop."""
    _stop_event.set()


def _scheduler_loop() -> None:
    """Check for due rescans on a fixed interval."""
    while not _stop_event.is_set():
        try:
            run_due_scans()
        except Exception:
            pass
        _stop_event.wait(CHECK_INTERVAL_SECONDS)


def run_due_scans() -> int:
    """Execute all due rescans and return the number attempted successfully."""
    conn = get_conn()
    try:
        init_db(conn)
        due_items = get_due_rescans(conn)
    finally:
        conn.close()

    count = 0
    for item in due_items:
        if _stop_event.is_set():
            break
        try:
            _rescan_url(item)
            count += 1
        except Exception:
            continue
    return count


def _rescan_url(item: dict) -> None:
    """Rescan a tracked URL and evaluate alert delivery."""
    url = str(item["url"])

    conn = get_conn()
    try:
        init_db(conn)
        history = get_url_history(conn, url, limit=2)
    finally:
        conn.close()
    previous_scan = history[0] if history else None

    fetch_result = fetch_html(url)
    analysis_url = fetch_result.final_url or url
    parsed = parse_content(fetch_result.html, analysis_url)
    geo = check_geo(parsed, fetch_result.html, analysis_url, fetch_result=fetch_result)

    scan_payload = {
        "geo": geo,
        "draft_mode": False,
        "stats": parsed.get("stats", {}),
        "readability": parsed.get("readability", {}),
        "schema_org": parsed.get("schema_org", {}),
        "parsed_snapshot": parsed,
    }
    scanned_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    conn = get_conn()
    try:
        init_db(conn)
        url_id = upsert_url(conn, analysis_url)
        save_scan(conn, url_id, scan_payload)
        mark_scan_completed(conn, url_id, scanned_at)
    finally:
        conn.close()

    webhook_url = str(item.get("webhook_url") or "")
    if not webhook_url:
        return

    current_score = int(geo.get("geo_score", {}).get("total", 0))
    current_grade = str(geo.get("geo_score", {}).get("grade", ""))
    evaluate_and_fire_webhook(
        url=analysis_url,
        url_id=url_id,
        webhook_url=webhook_url,
        alert_threshold=int(item.get("alert_threshold") or 0),
        current_score=current_score,
        current_grade=current_grade,
        previous_scan=previous_scan,
    )
