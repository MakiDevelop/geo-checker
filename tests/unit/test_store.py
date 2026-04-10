"""Tests for SQLite scan persistence."""
from __future__ import annotations

from copy import deepcopy

from src.db.store import (
    diff_scans,
    get_conn,
    get_scan_detail,
    get_url_history,
    init_db,
    save_scan,
    update_url_monitoring_with_audit,
    upsert_url,
)


def _sample_result() -> dict:
    return {
        "geo": {
            "geo_score": {
                "total": 72,
                "grade": "C",
                "grade_label": "Fair",
                "breakdown": {
                    "accessibility": {"score": 22, "max": 40, "percentage": 55},
                    "structure": {"score": 25, "max": 30, "percentage": 83},
                    "quality": {"score": 25, "max": 30, "percentage": 83},
                },
            },
            "summary": {
                "issues": {
                    "critical": [{"key": "crawlers_blocked", "crawlers": ["GPTBot"]}],
                    "warning": [{"key": "no_schema"}],
                    "good": [{"key": "strong_opening"}],
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
                    },
                    "claudebot": {
                        "status": "allow",
                        "display": "ClaudeBot",
                        "vendor": "Anthropic",
                        "purpose": "both",
                    },
                },
                "meta_robots": {"content": "", "noindex": False, "nofollow": False},
                "x_robots_tag": {"value": "", "noindex": False, "nofollow": False},
            },
        },
        "draft_mode": False,
    }


def test_store_persists_history_and_diff(tmp_path) -> None:
    """Scans should persist and produce meaningful diffs."""
    db_path = tmp_path / "geo_checker.db"
    conn = get_conn(db_path)
    init_db(conn)

    url_id = upsert_url(conn, "https://example.com/article")
    scan_a = save_scan(conn, url_id, _sample_result())

    improved = deepcopy(_sample_result())
    improved["geo"]["geo_score"]["total"] = 88
    improved["geo"]["geo_score"]["grade"] = "B"
    improved["geo"]["geo_score"]["grade_label"] = "Good"
    improved["geo"]["geo_score"]["breakdown"]["accessibility"]["score"] = 38
    improved["geo"]["geo_score"]["breakdown"]["accessibility"]["percentage"] = 95
    improved["geo"]["summary"]["issues"]["critical"] = []
    improved["geo"]["summary"]["issues"]["warning"] = [{"key": "no_author"}]
    improved["geo"]["summary"]["issues"]["good"] = [
        {"key": "strong_opening"},
        {"key": "has_article_schema"},
    ]
    improved["geo"]["ai_crawler_access"]["crawlers"]["gptbot"]["status"] = "allow"

    scan_b = save_scan(conn, url_id, improved)

    history = get_url_history(conn, "https://example.com/article")
    assert [item["scan_id"] for item in history[:2]] == [scan_b, scan_a]
    assert history[0]["dimensions"]["accessibility"]["score"] == 38

    detail = get_scan_detail(conn, scan_a)
    assert detail is not None
    assert detail["crawler_status"]["gptbot"]["status"] == "disallow"
    assert detail["findings"][0]["category"] == "crawlers_blocked"

    diff = diff_scans(conn, scan_a, scan_b)
    assert diff["score_delta"] == 16
    assert diff["dimension_deltas"]["accessibility"] == 16
    assert diff["crawler_changes"] == [
        {
            "crawler_key": "gptbot",
            "display": "GPTBot",
            "from": "disallow",
            "to": "allow",
        }
    ]
    assert any(issue["category"] == "no_author" for issue in diff["new_issues"])
    assert any(issue["category"] == "crawlers_blocked" for issue in diff["resolved_issues"])

    conn.close()


def test_update_url_monitoring_with_audit_persists_actor_and_webhook_diff(tmp_path) -> None:
    db_path = tmp_path / "geo_checker.db"
    conn = get_conn(db_path)
    init_db(conn)

    upsert_url(conn, "https://example.com/article")
    updated = update_url_monitoring_with_audit(
        conn,
        "https://example.com/article",
        webhook_url="https://hooks.example.com/updated",
        actor_key_name="CLIENT_A",
        actor_tier="premium",
        client_ip="203.0.113.10",
        action="update_monitoring",
        reason="manual update",
    )

    audit_row = conn.execute(
        """
        SELECT
            actor_key_name, actor_tier, client_ip, action,
            old_webhook_url, new_webhook_url, reason
        FROM monitoring_audit_log
        ORDER BY id DESC
        LIMIT 1
        """,
    ).fetchone()

    assert updated is True
    assert audit_row is not None
    assert audit_row["actor_key_name"] == "CLIENT_A"
    assert audit_row["actor_tier"] == "premium"
    assert audit_row["client_ip"] == "203.0.113.10"
    assert audit_row["action"] == "update_monitoring"
    assert audit_row["old_webhook_url"] == ""
    assert audit_row["new_webhook_url"] == "https://hooks.example.com/updated"
    assert audit_row["reason"] == "manual update"

    conn.close()
