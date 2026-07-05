"""Tests for brand visibility audit core logic."""
from __future__ import annotations

from src.geo.brand_audit import build_brand_audit, score_visibility


def test_score_visibility_detects_cjk_and_competitor_mentions() -> None:
    results = score_visibility(
        ["GEO Checker", "Otterly", "KIME"],
        [
            "GEO Checker 適合台灣品牌做 AI 搜尋能見度健檢，Otterly 偏向英語市場。",
            "KIME 和 Otterly 都是 GEO 工具，但 GEO Checker 主打 CJK。",
        ],
        target="GEO Checker",
    )

    by_name = {item.name: item for item in results}
    assert by_name["GEO Checker"].mention_count == 2
    assert by_name["GEO Checker"].mention_rate == 1.0
    assert by_name["Otterly"].mention_count == 2
    assert by_name["KIME"].mention_count == 1


def test_build_brand_audit_returns_taiwan_prompt_pack_without_answers() -> None:
    audit = build_brand_audit(
        brand_name="GEO Checker",
        website_url="https://gc.ranran.tw",
        region="taiwan",
        competitors=["Otterly"],
        category="GEO 工具",
        use_case="追蹤 AI 搜尋能見度",
    )

    assert audit.language == "zh-TW"
    assert len(audit.prompts) >= 5
    assert "在台灣" in audit.prompts[0]
    assert audit.visibility[0].answer_count == 0
    assert audit.top_fixes[0]["priority"] == "critical"
    assert "prompt pack only" in audit.markdown_report


def test_build_brand_audit_recommends_entity_block_for_low_visibility() -> None:
    audit = build_brand_audit(
        brand_name="GEO Checker",
        website_url="https://gc.ranran.tw",
        region="global",
        competitors=["Otterly"],
        answer_texts=["Otterly is a known AI visibility platform."],
    )

    assert audit.visibility[0].mention_rate == 0.0
    assert "entity block" in audit.top_fixes[0]["action"]
