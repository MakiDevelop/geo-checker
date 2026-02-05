"""
GEO Comparator - Multi-URL Comparison Logic

Compares GEO analysis results across multiple URLs to identify
differences and determine which page is most AI-friendly.
"""

from typing import Any


def _get_nested(data: dict, path: str, default: Any = None) -> Any:
    """Get nested value from dict using dot notation."""
    keys = path.split(".")
    value = data
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key, default)
        else:
            return default
    return value


def _format_value(value: Any) -> str:
    """Format a value for display in comparison."""
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        return f"{value:.1f}"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value[:3])
    return str(value)


def compare_results(results: dict[str, dict]) -> dict:
    """
    Compare multiple GEO analysis results.

    Args:
        results: Dict mapping URL IDs (e.g., "u1", "u2") to their analysis results

    Returns:
        Comparison result with summary, diffs, and winner
    """
    if len(results) < 2:
        return {"error": "Need at least 2 results to compare"}

    summary = {
        "coverage": {},
        "risk_flags": {},
        "winner": None,
        "grades": {},
    }

    diffs = []

    # Extract scores and grades
    for url_id, result in results.items():
        geo = result.get("geo", {})
        geo_score = geo.get("geo_score", {})

        # GEO Score
        total_score = geo_score.get("total", 0)
        summary["coverage"][url_id] = total_score

        # Grade
        grade = geo_score.get("grade", "F")
        summary["grades"][url_id] = grade

        # Risk flags (blockers count)
        blockers = geo.get("last_mile_blockers", [])
        summary["risk_flags"][url_id] = len(blockers)

    # Determine winner (highest score)
    if summary["coverage"]:
        winner = max(summary["coverage"], key=summary["coverage"].get)
        summary["winner"] = winner

    # Metrics to compare: (path, display_name, i18n_key)
    metrics_to_compare = [
        ("geo.geo_score.total", "GEO Score", "geo_score"),
        ("geo.geo_score.grade", "Grade", "grade"),
        ("geo.geo_score.breakdown.accessibility.score", "Accessibility", "accessibility"),
        ("geo.geo_score.breakdown.structure.score", "Structure", "structure"),
        ("geo.geo_score.breakdown.quality.score", "Quality", "quality"),
        ("readability.flesch_reading_ease", "Readability (Flesch)", "readability_flesch"),
        ("readability.flesch_kincaid_grade", "Reading Grade", "reading_grade"),
        ("stats.word_count", "Word Count", "word_count"),
        ("stats.heading_count", "Headings", "headings"),
        ("stats.paragraph_count", "Paragraphs", "paragraphs"),
        ("geo.extended_metrics.entity_count", "Entities", "entities"),
        ("geo.extended_metrics.citation_potential.level", "Citation Potential", "citation_potential"),
        ("geo.extended_metrics.qa_structure.has_qa_structure", "Has Q&A Structure", "qa_structure"),
        ("geo.extended_metrics.content_depth.has_deep_hierarchy", "Deep Hierarchy", "deep_hierarchy"),
        ("schema_org.types", "Schema Types", "schema_types"),
    ]

    for metric_path, metric_name, metric_key in metrics_to_compare:
        diff = {"metric": metric_name, "key": metric_key, "values": {}}
        for url_id, result in results.items():
            value = _get_nested(result, metric_path)
            diff["values"][url_id] = _format_value(value)
        diffs.append(diff)

    # Add crawler access comparison
    crawler_diff = {"metric": "AI Crawlers Allowed", "key": "ai_crawlers", "values": {}}
    for url_id, result in results.items():
        crawler = _get_nested(result, "geo.ai_crawler_access", {})
        allowed_count = sum(
            1 for bot in ["gptbot", "claudebot", "perplexitybot", "google_extended"]
            if crawler.get(bot) == "allow"
        )
        crawler_diff["values"][url_id] = f"{allowed_count}/4"
    diffs.insert(6, crawler_diff)  # Insert after Quality

    return {
        "summary": summary,
        "diffs": diffs,
        "url_ids": list(results.keys()),
    }


def get_comparison_insights(comparison: dict) -> list[str]:
    """
    Generate insights from comparison results.

    Args:
        comparison: Result from compare_results()

    Returns:
        List of insight strings
    """
    insights = []
    summary = comparison.get("summary", {})

    if not summary:
        return insights

    winner = summary.get("winner")
    coverage = summary.get("coverage", {})
    risk_flags = summary.get("risk_flags", {})
    grades = summary.get("grades", {})

    # Score difference insight
    if len(coverage) >= 2:
        scores = list(coverage.values())
        diff = max(scores) - min(scores)
        if diff > 20:
            insights.append(f"Significant GEO score gap: {diff} points difference")
        elif diff < 5:
            insights.append("Pages have similar GEO scores")

    # Risk flags insight
    max_risks = max(risk_flags.values()) if risk_flags else 0
    min_risks = min(risk_flags.values()) if risk_flags else 0
    if max_risks > min_risks:
        high_risk_id = max(risk_flags, key=risk_flags.get)
        insights.append(f"{high_risk_id} has more structural issues to address")

    # Grade insight
    if winner and winner in grades:
        winner_grade = grades[winner]
        if winner_grade in ["A", "B"]:
            insights.append(f"{winner} is already well-optimized for AI")
        elif winner_grade in ["D", "F"]:
            insights.append("All pages need significant improvement for AI visibility")

    return insights


def create_comparison_payload(
    urls: list[dict],
    results: dict[str, dict],
) -> dict:
    """
    Create the full comparison payload for API response.

    Args:
        urls: List of {"id": "u1", "url": "https://..."} dicts
        results: Dict mapping URL IDs to their analysis results

    Returns:
        Full comparison payload
    """
    comparison = compare_results(results)
    insights = get_comparison_insights(comparison)

    # Add URL info to the payload
    url_info = {item["id"]: item["url"] for item in urls}

    return {
        "urls": url_info,
        "comparison": comparison,
        "insights": insights,
    }
