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
