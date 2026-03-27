"""Fix Checklist Generator — turn analysis issues into actionable checklist."""
from __future__ import annotations

# Priority-ordered fix items with code snippets and guides
_FIX_ITEMS: dict[str, dict] = {
    "update_robots_txt": {
        "title": "Allow AI crawlers in robots.txt",
        "priority": "critical",
        "impact": "high",
        "category": "accessibility",
        "guide": (
            "Add explicit Allow rules for AI crawlers in your "
            "robots.txt file. Use the generated robots.txt below."
        ),
        "has_generator": True,
    },
    "remove_noindex": {
        "title": "Remove noindex directive",
        "priority": "critical",
        "impact": "high",
        "category": "accessibility",
        "guide": (
            "Remove the noindex meta tag or X-Robots-Tag header "
            "that prevents AI from indexing this page."
        ),
        "code": '<meta name="robots" content="index, follow">',
    },
    "add_schema": {
        "title": "Add Schema.org structured data",
        "priority": "recommended",
        "impact": "high",
        "category": "structure",
        "guide": (
            "Add JSON-LD structured data to help AI understand "
            "your content type. Use the generated schema below."
        ),
        "has_generator": True,
    },
    "add_author_info": {
        "title": "Add author information (E-E-A-T)",
        "priority": "recommended",
        "impact": "medium",
        "category": "eeat",
        "guide": (
            "Add author metadata so AI can assess content "
            "authority. Include name, bio, and credentials."
        ),
        "code": '<meta name="author" content="Your Name">',
    },
    "add_date_metadata": {
        "title": "Add publication/modification dates",
        "priority": "recommended",
        "impact": "medium",
        "category": "freshness",
        "guide": (
            "Add datePublished and dateModified to help AI "
            "assess content freshness. Recent content gets "
            "3.2x more citations."
        ),
        "code": (
            '<meta property="article:published_time" '
            'content="2026-01-01T00:00:00Z">\n'
            '<meta property="article:modified_time" '
            'content="2026-03-27T00:00:00Z">'
        ),
    },
    "add_h_framing": {
        "title": "Add clear heading structure",
        "priority": "recommended",
        "impact": "medium",
        "category": "structure",
        "guide": (
            "Add H1 for main title, H2 for sections, "
            "H3 for subsections. Use question-format headings "
            "for FAQ-style content."
        ),
    },
    "add_fact_list": {
        "title": "Add enumerable facts (lists/tables)",
        "priority": "recommended",
        "impact": "medium",
        "category": "structure",
        "guide": (
            "Add bullet lists, numbered lists, or tables "
            "with specific data points. AI loves structured, "
            "enumerable facts."
        ),
    },
    "improve_alt_text": {
        "title": "Add descriptive image alt text",
        "priority": "suggested",
        "impact": "low",
        "category": "accessibility",
        "guide": (
            "Add descriptive alt text (3+ words) to all "
            "images. AI multimodal models use alt text to "
            "understand visual content."
        ),
    },
    "expand_content": {
        "title": "Expand content depth",
        "priority": "suggested",
        "impact": "medium",
        "category": "quality",
        "guide": (
            "Aim for 500+ words with comprehensive coverage. "
            "AI prefers thorough content over thin pages."
        ),
    },
    "improve_readability": {
        "title": "Improve readability",
        "priority": "suggested",
        "impact": "low",
        "category": "quality",
        "guide": (
            "Simplify sentences, use shorter paragraphs, "
            "and add clear definitions for technical terms."
        ),
    },
    "improve_first_paragraph": {
        "title": "Strengthen first paragraph",
        "priority": "suggested",
        "impact": "medium",
        "category": "quality",
        "guide": (
            "Make the first paragraph a clear summary that "
            "directly answers the main topic. AI often cites "
            "the opening paragraph."
        ),
    },
    "reduce_pronouns": {
        "title": "Reduce ambiguous pronouns",
        "priority": "suggested",
        "impact": "low",
        "category": "quality",
        "guide": (
            "Replace 'this', 'it', 'they' with specific "
            "nouns. When AI extracts sentences out of context, "
            "ambiguous pronouns lose meaning."
        ),
    },
}


def generate_checklist(geo_result: dict) -> list[dict]:
    """Generate an ordered fix checklist from GEO analysis results.

    Returns list of checklist items with:
    - id, title, priority, impact, category
    - guide (explanation)
    - code (optional code snippet)
    - has_generator (links to robots.txt or schema generator)
    - completed (always False, toggled by frontend)
    """
    summary = geo_result.get("summary", {})
    issues = summary.get("issues", {})
    priority_fixes = summary.get("priority_fixes", [])

    # Collect all issue keys that need fixing
    fix_actions: set[str] = set()
    for fix in priority_fixes:
        fix_actions.add(fix.get("action", ""))

    # Also check warnings for additional items
    for issue in issues.get("warning", []):
        key = issue.get("key", "")
        # Map issue keys to fix actions
        issue_to_fix = {
            "no_schema": "add_schema",
            "weak_entry": "add_h_framing",
            "no_facts": "add_fact_list",
            "low_readability": "improve_readability",
            "thin_content": "expand_content",
            "weak_opening": "improve_first_paragraph",
            "unclear_pronouns": "reduce_pronouns",
            "no_date_signals": "add_date_metadata",
            "no_author": "add_author_info",
            "poor_alt_text": "improve_alt_text",
        }
        if key in issue_to_fix:
            fix_actions.add(issue_to_fix[key])

    # Check critical issues
    for issue in issues.get("critical", []):
        key = issue.get("key", "")
        if key == "crawlers_blocked":
            fix_actions.add("update_robots_txt")
        elif key == "noindex_set":
            fix_actions.add("remove_noindex")

    # Build ordered checklist
    checklist = []
    priority_order = {"critical": 0, "recommended": 1, "suggested": 2}

    for action_id, item in _FIX_ITEMS.items():
        if action_id in fix_actions:
            checklist.append({
                "id": action_id,
                "title": item["title"],
                "priority": item["priority"],
                "impact": item["impact"],
                "category": item["category"],
                "guide": item["guide"],
                "code": item.get("code", ""),
                "has_generator": item.get("has_generator", False),
                "completed": False,
            })

    # Sort by priority
    checklist.sort(
        key=lambda x: priority_order.get(x["priority"], 99)
    )

    return checklist
