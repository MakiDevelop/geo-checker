"""SQLite persistence layer for GEO scan history."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path("data/geo_checker.db")

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS urls (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        url         TEXT NOT NULL UNIQUE,
        label       TEXT DEFAULT '',
        rescan_cron TEXT DEFAULT '',
        created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
        updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS monitoring_audit_log (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        url_id              INTEGER NOT NULL REFERENCES urls(id) ON DELETE CASCADE,
        url                 TEXT NOT NULL,
        actor_key_name      TEXT NOT NULL DEFAULT '',
        actor_tier          TEXT NOT NULL DEFAULT '',
        client_ip           TEXT NOT NULL DEFAULT '',
        action              TEXT NOT NULL,
        old_webhook_url     TEXT NOT NULL DEFAULT '',
        new_webhook_url     TEXT NOT NULL DEFAULT '',
        created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
        reason              TEXT NOT NULL DEFAULT ''
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS idx_monitoring_audit_url_id "
        "ON monitoring_audit_log(url_id)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_monitoring_audit_created_at "
        "ON monitoring_audit_log(created_at)"
    ),
    """
    CREATE TABLE IF NOT EXISTS scans (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        url_id          INTEGER NOT NULL REFERENCES urls(id) ON DELETE CASCADE,
        total_score     INTEGER NOT NULL,
        grade           TEXT NOT NULL,
        grade_label     TEXT NOT NULL DEFAULT '',
        draft_mode      INTEGER NOT NULL DEFAULT 0,
        scanned_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_scans_url_id ON scans(url_id)",
    "CREATE INDEX IF NOT EXISTS idx_scans_scanned_at ON scans(scanned_at)",
    """
    CREATE TABLE IF NOT EXISTS scan_dimensions (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        scan_id     INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
        dimension   TEXT NOT NULL,
        score       INTEGER NOT NULL,
        max_score   INTEGER NOT NULL,
        percentage  INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_dims_scan_id ON scan_dimensions(scan_id)",
    """
    CREATE TABLE IF NOT EXISTS scan_findings (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        scan_id         INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
        category        TEXT NOT NULL DEFAULT '',
        severity        TEXT NOT NULL,
        message         TEXT NOT NULL DEFAULT '',
        details_json    TEXT DEFAULT '{}'
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_findings_scan_id ON scan_findings(scan_id)",
    """
    CREATE TABLE IF NOT EXISTS scan_crawler_status (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        scan_id     INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
        crawler_key TEXT NOT NULL,
        display     TEXT NOT NULL,
        vendor      TEXT NOT NULL,
        purpose     TEXT NOT NULL,
        status      TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_crawler_scan_id ON scan_crawler_status(scan_id)",
)

_MIGRATIONS = (
    "ALTER TABLE urls ADD COLUMN webhook_url TEXT DEFAULT ''",
    "ALTER TABLE urls ADD COLUMN alert_threshold INTEGER DEFAULT 0",
    "ALTER TABLE urls ADD COLUMN last_scanned_at TEXT DEFAULT ''",
    "ALTER TABLE urls ADD COLUMN last_alert_at TEXT DEFAULT ''",
)

_ISSUE_MESSAGES = {
    "crawlers_blocked": "AI crawlers are blocked by robots.txt",
    "noindex_set": "Page has noindex directive - AI cannot index",
    "no_schema": "No Schema.org structured data found",
    "weak_entry": "Weak narrative entry (missing H1/H2 or meta description)",
    "no_facts": "No enumerable facts (lists/tables) found",
    "low_readability": "Content readability is low",
    "thin_content": "Content is too thin (< 300 words)",
    "weak_opening": "First paragraph could be stronger",
    "unclear_pronouns": "Too many ambiguous pronouns",
    "has_faq_schema": "FAQPage schema detected",
    "has_article_schema": "Article schema detected",
    "has_breadcrumb_schema": "BreadcrumbList schema detected",
    "good_lists": "Good use of lists for content organization",
    "good_definitions": "Good definition density",
    "quotable_content": "Contains quotable sentences",
    "quotable_diversity": "Multiple types of quotable content",
    "qa_structure": "Q&A structure detected",
    "comprehensive_content": "Comprehensive content (1000+ words)",
    "strong_opening": "Strong opening paragraph",
    "clear_pronouns": "Clear pronoun usage",
    "high_citation_potential": "High AI citation potential",
    "entity_rich": "Rich in named entities",
    "has_date_signals": "Publication/modification dates present",
    "no_date_signals": "No date signals (datePublished/dateModified)",
    "author_identified": "Content author identified",
    "no_author": "No author information found",
    "good_alt_text": "Good image alt text coverage",
    "poor_alt_text": "Some images missing alt text",
}


def get_conn(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Return a SQLite connection with WAL and foreign keys enabled."""
    path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    # Wait up to 5s for a locked write (scheduler + API writers can overlap).
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create all SQLite tables and indexes if they do not exist."""
    for statement in _SCHEMA_STATEMENTS:
        conn.execute(statement)
    for migration in _MIGRATIONS:
        try:
            conn.execute(migration)
        except sqlite3.OperationalError:
            pass
    conn.commit()


def upsert_url(
    conn: sqlite3.Connection,
    url: str,
    *,
    label: str = "",
    rescan_cron: str = "",
) -> int:
    """Insert or update a URL record and return its ID."""
    conn.execute(
        """
        INSERT INTO urls (url, label, rescan_cron)
        VALUES (?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET
            label = CASE
                WHEN excluded.label <> '' THEN excluded.label
                ELSE urls.label
            END,
            rescan_cron = CASE
                WHEN excluded.rescan_cron <> '' THEN excluded.rescan_cron
                ELSE urls.rescan_cron
            END,
            updated_at = (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        """,
        (url, label, rescan_cron),
    )
    row = conn.execute("SELECT id FROM urls WHERE url = ?", (url,)).fetchone()
    conn.commit()
    if row is None:
        raise ValueError(f"Could not upsert URL: {url}")
    return int(row["id"])


def save_scan(conn: sqlite3.Connection, url_id: int, geo_result: dict) -> int:
    """Persist a GEO analysis result and return the created scan ID."""
    root = geo_result
    geo = root.get("geo", root)
    geo_score = geo.get("geo_score", {})

    cursor = conn.execute(
        """
        INSERT INTO scans (url_id, total_score, grade, grade_label, draft_mode)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            url_id,
            int(geo_score.get("total", 0)),
            str(geo_score.get("grade", "F")),
            str(geo_score.get("grade_label", "")),
            1 if root.get("draft_mode", False) else 0,
        ),
    )
    scan_id = int(cursor.lastrowid)

    breakdown = geo_score.get("breakdown", {})
    dimension_rows = []
    for dimension, values in breakdown.items():
        dimension_rows.append(
            (
                scan_id,
                dimension,
                int(values.get("score", 0)),
                int(values.get("max", values.get("max_score", 0))),
                int(values.get("percentage", 0)),
            )
        )
    if dimension_rows:
        conn.executemany(
            """
            INSERT INTO scan_dimensions (scan_id, dimension, score, max_score, percentage)
            VALUES (?, ?, ?, ?, ?)
            """,
            dimension_rows,
        )

    summary = geo.get("summary", {})
    issues = summary.get("issues", {})
    finding_rows = []
    for severity in ("critical", "warning", "good"):
        for issue in issues.get(severity, []):
            category = str(issue.get("key", ""))
            finding_rows.append(
                (
                    scan_id,
                    category,
                    severity,
                    _ISSUE_MESSAGES.get(category, category.replace("_", " ").strip()),
                    json.dumps(issue, ensure_ascii=False, sort_keys=True),
                )
            )
    if finding_rows:
        conn.executemany(
            """
            INSERT INTO scan_findings (scan_id, category, severity, message, details_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            finding_rows,
        )

    crawler_rows = []
    ai_access = geo.get("ai_crawler_access", {})
    for crawler_key, info in ai_access.get("crawlers", {}).items():
        crawler_rows.append(
            (
                scan_id,
                crawler_key,
                str(info.get("display", crawler_key)),
                str(info.get("vendor", "")),
                str(info.get("purpose", "")),
                str(info.get("status", "unspecified")),
            )
        )
    if crawler_rows:
        conn.executemany(
            """
            INSERT INTO scan_crawler_status (
                scan_id, crawler_key, display, vendor, purpose, status
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            crawler_rows,
        )

    conn.commit()
    return scan_id


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _insert_monitoring_audit_row(
    conn: sqlite3.Connection,
    *,
    url_id: int,
    url: str,
    actor_key_name: str,
    actor_tier: str,
    client_ip: str,
    action: str,
    old_webhook_url: str,
    new_webhook_url: str,
    created_at: str,
    reason: str,
) -> None:
    conn.execute(
        """
        INSERT INTO monitoring_audit_log (
            url_id,
            url,
            actor_key_name,
            actor_tier,
            client_ip,
            action,
            old_webhook_url,
            new_webhook_url,
            created_at,
            reason
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            url_id,
            url,
            actor_key_name,
            actor_tier,
            client_ip,
            action,
            old_webhook_url,
            new_webhook_url,
            created_at,
            reason,
        ),
    )


def _update_url_monitoring_transaction(
    conn: sqlite3.Connection,
    url: str,
    *,
    rescan_cron: str | None = None,
    webhook_url: str | None = None,
    alert_threshold: int | None = None,
    audit_entry: dict[str, str] | None = None,
) -> bool:
    row = conn.execute(
        "SELECT id, url, webhook_url FROM urls WHERE url = ?",
        (url,),
    ).fetchone()
    if row is None:
        return False

    # Allowlist of columns that may appear in the dynamic UPDATE.
    # Defense-in-depth: prevents a future edit from accidentally introducing
    # user-controlled column names into the f-string below.
    _ALLOWED_UPDATE_COLUMNS = frozenset(
        {"rescan_cron", "webhook_url", "alert_threshold", "updated_at"}
    )

    updates: list[str] = []
    values: list[Any] = []

    if rescan_cron is not None:
        updates.append("rescan_cron = ?")
        values.append(rescan_cron)
    if webhook_url is not None:
        updates.append("webhook_url = ?")
        values.append(webhook_url)
    if alert_threshold is not None:
        updates.append("alert_threshold = ?")
        values.append(int(alert_threshold))

    if not updates and audit_entry is None:
        return True

    url_id = int(row["id"])
    current_timestamp = _utc_now()
    old_webhook_url = str(row["webhook_url"] or "")
    new_webhook_url = old_webhook_url if webhook_url is None else webhook_url

    with conn:
        if updates:
            updates.append("updated_at = ?")
            values.append(current_timestamp)
            values.append(url)
            # Verify every fragment references an allowlisted column before
            # interpolating into SQL. Each fragment must be "<col> = ?".
            for fragment in updates:
                col = fragment.split(" = ", 1)[0]
                if col not in _ALLOWED_UPDATE_COLUMNS:
                    raise ValueError(f"Refusing to UPDATE unknown column: {col!r}")
            cursor = conn.execute(
                f"UPDATE urls SET {', '.join(updates)} WHERE url = ?",
                values,
            )
            updated = cursor.rowcount > 0
        else:
            updated = True

        if audit_entry is not None:
            _insert_monitoring_audit_row(
                conn,
                url_id=url_id,
                url=str(row["url"]),
                actor_key_name=audit_entry.get("actor_key_name", ""),
                actor_tier=audit_entry.get("actor_tier", ""),
                client_ip=audit_entry.get("client_ip", ""),
                action=audit_entry.get("action", "update_monitoring"),
                old_webhook_url=old_webhook_url,
                new_webhook_url=new_webhook_url,
                created_at=current_timestamp,
                reason=audit_entry.get("reason", ""),
            )

    return updated


def update_url_monitoring(
    conn: sqlite3.Connection,
    url: str,
    *,
    rescan_cron: str | None = None,
    webhook_url: str | None = None,
    alert_threshold: int | None = None,
) -> bool:
    """Update monitoring settings for a tracked URL."""
    return _update_url_monitoring_transaction(
        conn,
        url,
        rescan_cron=rescan_cron,
        webhook_url=webhook_url,
        alert_threshold=alert_threshold,
    )


def update_url_monitoring_with_audit(
    conn: sqlite3.Connection,
    url: str,
    *,
    rescan_cron: str | None = None,
    webhook_url: str | None = None,
    alert_threshold: int | None = None,
    actor_key_name: str = "",
    actor_tier: str = "",
    client_ip: str = "",
    action: str = "update_monitoring",
    reason: str = "",
) -> bool:
    """Update monitoring settings and persist an audit row in one transaction."""
    return _update_url_monitoring_transaction(
        conn,
        url,
        rescan_cron=rescan_cron,
        webhook_url=webhook_url,
        alert_threshold=alert_threshold,
        audit_entry={
            "actor_key_name": actor_key_name,
            "actor_tier": actor_tier,
            "client_ip": client_ip,
            "action": action,
            "reason": reason,
        },
    )


def log_monitoring_audit_event(
    conn: sqlite3.Connection,
    *,
    url: str,
    actor_key_name: str = "",
    actor_tier: str = "",
    client_ip: str = "",
    action: str,
    old_webhook_url: str = "",
    new_webhook_url: str = "",
    reason: str = "",
) -> bool:
    """Persist a monitoring audit row without modifying the URL configuration."""
    row = conn.execute(
        "SELECT id, url FROM urls WHERE url = ?",
        (url,),
    ).fetchone()
    if row is None:
        return False

    with conn:
        _insert_monitoring_audit_row(
            conn,
            url_id=int(row["id"]),
            url=str(row["url"]),
            actor_key_name=actor_key_name,
            actor_tier=actor_tier,
            client_ip=client_ip,
            action=action,
            old_webhook_url=old_webhook_url,
            new_webhook_url=new_webhook_url,
            created_at=_utc_now(),
            reason=reason,
        )
    return True


def get_url_monitoring(conn: sqlite3.Connection, url: str) -> dict | None:
    """Return monitoring configuration for a tracked URL."""
    row = conn.execute(
        """
        SELECT rescan_cron, webhook_url, alert_threshold, last_scanned_at, last_alert_at
        FROM urls
        WHERE url = ?
        """,
        (url,),
    ).fetchone()
    if row is None:
        return None

    return {
        "rescan_cron": str(row["rescan_cron"] or ""),
        "webhook_url": str(row["webhook_url"] or ""),
        "alert_threshold": int(row["alert_threshold"] or 0),
        "last_scanned_at": str(row["last_scanned_at"] or ""),
        "last_alert_at": str(row["last_alert_at"] or ""),
    }


def mark_scan_completed(conn: sqlite3.Connection, url_id: int, scanned_at: str) -> None:
    """Update last_scanned_at after a successful scheduler scan."""
    conn.execute(
        """
        UPDATE urls
        SET
            last_scanned_at = ?,
            updated_at = (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        WHERE id = ?
        """,
        (scanned_at, url_id),
    )
    conn.commit()


def mark_alert_sent(conn: sqlite3.Connection, url_id: int, alerted_at: str) -> None:
    """Update last_alert_at after a successful webhook delivery."""
    conn.execute(
        """
        UPDATE urls
        SET
            last_alert_at = ?,
            updated_at = (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        WHERE id = ?
        """,
        (alerted_at, url_id),
    )
    conn.commit()


def get_due_rescans(conn: sqlite3.Connection) -> list[dict]:
    """Return tracked URLs whose simplified rescan interval is due."""
    intervals = {
        "hourly": 3600,
        "daily": 86400,
        "weekly": 604800,
    }
    now = datetime.now(UTC)
    rows = conn.execute(
        """
        SELECT
            id AS url_id,
            url,
            rescan_cron,
            webhook_url,
            alert_threshold,
            last_scanned_at
        FROM urls
        WHERE rescan_cron IN ('hourly', 'daily', 'weekly')
        ORDER BY id ASC
        """
    ).fetchall()

    due_items: list[dict] = []
    for row in rows:
        cron = str(row["rescan_cron"] or "")
        interval_seconds = intervals.get(cron)
        if interval_seconds is None:
            continue

        last_scanned_at = str(row["last_scanned_at"] or "")
        if not last_scanned_at:
            due_items.append(
                {
                    "url_id": int(row["url_id"]),
                    "url": str(row["url"]),
                    "rescan_cron": cron,
                    "webhook_url": str(row["webhook_url"] or ""),
                    "alert_threshold": int(row["alert_threshold"] or 0),
                    "last_scanned_at": "",
                }
            )
            continue

        parsed = _parse_iso8601(last_scanned_at)
        if parsed is None:
            due_items.append(
                {
                    "url_id": int(row["url_id"]),
                    "url": str(row["url"]),
                    "rescan_cron": cron,
                    "webhook_url": str(row["webhook_url"] or ""),
                    "alert_threshold": int(row["alert_threshold"] or 0),
                    "last_scanned_at": last_scanned_at,
                }
            )
            continue

        if (now - parsed).total_seconds() >= interval_seconds:
            due_items.append(
                {
                    "url_id": int(row["url_id"]),
                    "url": str(row["url"]),
                    "rescan_cron": cron,
                    "webhook_url": str(row["webhook_url"] or ""),
                    "alert_threshold": int(row["alert_threshold"] or 0),
                    "last_scanned_at": last_scanned_at,
                }
            )

    return due_items


def get_url_history(conn: sqlite3.Connection, url: str, *, limit: int = 20) -> list[dict]:
    """Return recent scan history for a URL, newest first."""
    rows = conn.execute(
        """
        SELECT s.id AS scan_id, s.total_score, s.grade, s.scanned_at
        FROM scans AS s
        JOIN urls AS u ON u.id = s.url_id
        WHERE u.url = ?
        ORDER BY s.scanned_at DESC, s.id DESC
        LIMIT ?
        """,
        (url, limit),
    ).fetchall()

    scan_ids = [int(row["scan_id"]) for row in rows]
    dimensions_by_scan = _load_dimensions(conn, scan_ids)

    history = []
    for row in rows:
        scan_id = int(row["scan_id"])
        history.append(
            {
                "scan_id": scan_id,
                "total_score": int(row["total_score"]),
                "grade": str(row["grade"]),
                "dimensions": dimensions_by_scan.get(scan_id, {}),
                "scanned_at": str(row["scanned_at"]),
            }
        )
    return history


def get_scan_detail(conn: sqlite3.Connection, scan_id: int) -> dict | None:
    """Return a full scan detail record including findings and crawler status."""
    row = conn.execute(
        """
        SELECT
            s.id AS scan_id,
            s.url_id,
            u.url,
            u.label,
            u.rescan_cron,
            s.total_score,
            s.grade,
            s.grade_label,
            s.draft_mode,
            s.scanned_at
        FROM scans AS s
        JOIN urls AS u ON u.id = s.url_id
        WHERE s.id = ?
        """,
        (scan_id,),
    ).fetchone()
    if row is None:
        return None

    findings = []
    for finding_row in conn.execute(
        """
        SELECT id, category, severity, message, details_json
        FROM scan_findings
        WHERE scan_id = ?
        ORDER BY
            CASE severity
                WHEN 'critical' THEN 0
                WHEN 'warning' THEN 1
                ELSE 2
            END,
            id
        """,
        (scan_id,),
    ).fetchall():
        findings.append(
            {
                "id": int(finding_row["id"]),
                "category": str(finding_row["category"]),
                "severity": str(finding_row["severity"]),
                "message": str(finding_row["message"]),
                "details": _loads_json(finding_row["details_json"]),
            }
        )

    crawler_status = {}
    for crawler_row in conn.execute(
        """
        SELECT crawler_key, display, vendor, purpose, status
        FROM scan_crawler_status
        WHERE scan_id = ?
        ORDER BY crawler_key
        """,
        (scan_id,),
    ).fetchall():
        crawler_status[str(crawler_row["crawler_key"])] = {
            "display": str(crawler_row["display"]),
            "vendor": str(crawler_row["vendor"]),
            "purpose": str(crawler_row["purpose"]),
            "status": str(crawler_row["status"]),
        }

    return {
        "scan_id": int(row["scan_id"]),
        "url_id": int(row["url_id"]),
        "url": str(row["url"]),
        "label": str(row["label"]),
        "rescan_cron": str(row["rescan_cron"]),
        "total_score": int(row["total_score"]),
        "grade": str(row["grade"]),
        "grade_label": str(row["grade_label"]),
        "draft_mode": bool(row["draft_mode"]),
        "scanned_at": str(row["scanned_at"]),
        "dimensions": _load_dimensions(conn, [scan_id]).get(scan_id, {}),
        "findings": findings,
        "crawler_status": crawler_status,
    }


def diff_scans(conn: sqlite3.Connection, scan_id_a: int, scan_id_b: int) -> dict:
    """Compare scan B against scan A and return deltas."""
    detail_a = get_scan_detail(conn, scan_id_a)
    detail_b = get_scan_detail(conn, scan_id_b)
    if detail_a is None:
        raise ValueError(f"Scan not found: {scan_id_a}")
    if detail_b is None:
        raise ValueError(f"Scan not found: {scan_id_b}")

    dimensions = sorted(set(detail_a["dimensions"]) | set(detail_b["dimensions"]))
    dimension_deltas = {
        dimension: int(detail_b["dimensions"].get(dimension, {}).get("score", 0))
        - int(detail_a["dimensions"].get(dimension, {}).get("score", 0))
        for dimension in dimensions
    }

    crawler_keys = sorted(set(detail_a["crawler_status"]) | set(detail_b["crawler_status"]))
    crawler_changes = []
    for crawler_key in crawler_keys:
        crawler_a = detail_a["crawler_status"].get(crawler_key, {})
        crawler_b = detail_b["crawler_status"].get(crawler_key, {})
        status_a = crawler_a.get("status", "unspecified")
        status_b = crawler_b.get("status", "unspecified")
        if status_a == status_b:
            continue
        crawler_changes.append(
            {
                "crawler_key": crawler_key,
                "display": crawler_b.get("display") or crawler_a.get("display", crawler_key),
                "from": status_a,
                "to": status_b,
            }
        )

    findings_a = {_finding_signature(item): item for item in detail_a["findings"]}
    findings_b = {_finding_signature(item): item for item in detail_b["findings"]}
    new_issue_keys = sorted(set(findings_b) - set(findings_a))
    resolved_issue_keys = sorted(set(findings_a) - set(findings_b))

    return {
        "score_delta": detail_b["total_score"] - detail_a["total_score"],
        "dimension_deltas": dimension_deltas,
        "crawler_changes": list(crawler_changes),
        "new_issues": [findings_b[key] for key in new_issue_keys],
        "resolved_issues": [findings_a[key] for key in resolved_issue_keys],
    }


def _load_dimensions(
    conn: sqlite3.Connection,
    scan_ids: list[int],
) -> dict[int, dict[str, dict[str, int]]]:
    if not scan_ids:
        return {}

    placeholders = ",".join("?" for _ in scan_ids)
    rows = conn.execute(
        f"""
        SELECT scan_id, dimension, score, max_score, percentage
        FROM scan_dimensions
        WHERE scan_id IN ({placeholders})
        ORDER BY id
        """,
        scan_ids,
    ).fetchall()

    grouped: dict[int, dict[str, dict[str, int]]] = {}
    for row in rows:
        grouped.setdefault(int(row["scan_id"]), {})[str(row["dimension"])] = {
            "score": int(row["score"]),
            "max_score": int(row["max_score"]),
            "percentage": int(row["percentage"]),
        }
    return grouped


def _finding_signature(finding: dict[str, Any]) -> tuple[str, str, str]:
    details = finding.get("details", {})
    return (
        str(finding.get("severity", "")),
        str(finding.get("category", "")),
        json.dumps(details, ensure_ascii=False, sort_keys=True),
    )


def _loads_json(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        loaded = json.loads(str(raw))
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _parse_iso8601(value: str) -> datetime | None:
    normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed
