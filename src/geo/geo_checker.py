"""GEO rule checks (v2.0.0) - Enhanced with weighted scoring."""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

_AGENT_MAP = {
    "gptbot": "GPTBot",
    "claudebot": "ClaudeBot",
    "perplexitybot": "PerplexityBot",
    "google-extended": "Google-Extended",
}


@dataclass
class _RobotsGroup:
    agents: list[str]
    rules: list[tuple[str, str]]


def _is_url(source: str) -> bool:
    parsed = urlparse(source)
    return parsed.scheme in {"http", "https"}


def _fetch_robots_txt(url: str) -> tuple[bool, str]:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        response = requests.get(robots_url, timeout=10)
        if response.status_code != 200:
            return False, ""
        return True, response.text
    except requests.RequestException:
        return False, ""


def _parse_robots_txt(text: str) -> list[_RobotsGroup]:
    groups: list[_RobotsGroup] = []
    current_agents: list[str] = []
    current_rules: list[tuple[str, str]] = []

    def _flush():
        if current_agents or current_rules:
            groups.append(_RobotsGroup(current_agents[:], current_rules[:]))
            current_agents.clear()
            current_rules.clear()

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            continue
        key, value = [part.strip() for part in line.split(":", 1)]
        key_lower = key.lower()
        if key_lower == "user-agent":
            if current_rules:
                _flush()
            current_agents.append(value.lower())
        elif key_lower in {"allow", "disallow"}:
            current_rules.append((key_lower, value))
    _flush()
    return groups


def _select_group(groups: Iterable[_RobotsGroup], agent: str) -> list[_RobotsGroup]:
    agent = agent.lower()
    matched = [group for group in groups if agent in group.agents]
    if matched:
        return matched
    return [group for group in groups if "*" in group.agents]


def _evaluate_group(groups: Iterable[_RobotsGroup], path: str) -> str:
    best_rule = None
    best_length = -1
    for group in groups:
        for rule_type, rule_path in group.rules:
            if rule_path == "":
                if rule_type == "disallow" and best_length < 0:
                    best_rule = "allow"
                    best_length = 0
                continue
            if path.startswith(rule_path):
                rule_length = len(rule_path)
                if rule_length > best_length:
                    best_length = rule_length
                    best_rule = rule_type
                elif rule_length == best_length and rule_type == "allow":
                    best_rule = rule_type
    if best_rule == "allow":
        return "allow"
    if best_rule == "disallow":
        return "disallow"
    return "unspecified"


def _extract_meta_robots(html: str) -> dict:
    soup = BeautifulSoup(html or "", "lxml")
    meta = soup.find("meta", attrs={"name": lambda value: value and value.lower() == "robots"})
    content = meta.get("content", "") if meta else ""
    content_lower = content.lower()
    return {
        "content": content,
        "noindex": "noindex" in content_lower,
        "nofollow": "nofollow" in content_lower,
    }


def _extract_x_robots(url: str) -> dict:
    if not _is_url(url):
        return {"value": "", "noindex": False, "nofollow": False}
    try:
        response = requests.get(url, timeout=10)
    except requests.RequestException:
        return {"value": "", "noindex": False, "nofollow": False}
    header = response.headers.get("X-Robots-Tag", "")
    header_lower = header.lower()
    return {
        "value": header,
        "noindex": "noindex" in header_lower,
        "nofollow": "nofollow" in header_lower,
    }


def _ai_crawler_access(url: str, html: str) -> dict:
    if not _is_url(url):
        return {
            "robots_txt_found": False,
            "gptbot": "unspecified",
            "claudebot": "unspecified",
            "perplexitybot": "unspecified",
            "google_extended": "unspecified",
            "meta_robots": _extract_meta_robots(html),
            "x_robots_tag": _extract_x_robots(url),
            "notes": "Non-URL input; robots.txt not checked.",
        }

    found, robots_text = _fetch_robots_txt(url)
    groups = _parse_robots_txt(robots_text) if found else []
    parsed = urlparse(url)
    path = parsed.path or "/"
    statuses = {}
    for key, agent in _AGENT_MAP.items():
        matched_groups = _select_group(groups, agent) if groups else []
        statuses[key] = _evaluate_group(matched_groups, path) if matched_groups else "unspecified"

    meta_robots = _extract_meta_robots(html)
    x_robots = _extract_x_robots(url)
    notes = []
    if not found:
        notes.append("robots.txt not found or unreadable.")
    if meta_robots["noindex"] or meta_robots["nofollow"]:
        notes.append("meta robots contains noindex/nofollow.")
    if x_robots["noindex"] or x_robots["nofollow"]:
        notes.append("X-Robots-Tag contains noindex/nofollow.")
    return {
        "robots_txt_found": found,
        "gptbot": statuses["gptbot"],
        "claudebot": statuses["claudebot"],
        "perplexitybot": statuses["perplexitybot"],
        "google_extended": statuses["google-extended"],
        "meta_robots": meta_robots,
        "x_robots_tag": x_robots,
        "notes": " ".join(notes) if notes else "No blocking signals detected in robots settings.",
    }


def _draft_mode_ai_access() -> dict:
    """Return a neutral ai_access result for draft mode (no penalties)."""
    return {
        "robots_txt_found": False,
        "gptbot": "unspecified",
        "claudebot": "unspecified",
        "perplexitybot": "unspecified",
        "google_extended": "unspecified",
        "meta_robots": {"content": "", "noindex": False, "nofollow": False},
        "x_robots_tag": {"value": "", "noindex": False, "nofollow": False},
        "notes": "Draft mode: accessibility checks skipped.",
    }


def _structural_diversity(components: dict) -> int:
    keys = ["heading_blocks", "paragraph_blocks", "list_blocks", "table_blocks"]
    return sum(1 for key in keys if components.get(key, 0) > 0)


def _interpretation_type(components: dict, stats: dict, entities_count: int) -> dict:
    list_blocks = components.get("list_blocks", 0)
    table_blocks = components.get("table_blocks", 0)
    paragraph_blocks = components.get("paragraph_blocks", 0)
    definition_blocks = components.get("definition_blocks", 0)
    diversity = _structural_diversity(components)

    enumeratable = list_blocks > 0 or table_blocks > 0
    reference_signals = 0
    conceptual_signals = 0

    if enumeratable:
        reference_signals += 1
    if table_blocks > 0:
        reference_signals += 1
    if definition_blocks > 0:
        reference_signals += 1
    if entities_count > 0 and definition_blocks > 0:
        reference_signals += 1
    if diversity >= 3:
        reference_signals += 1

    if paragraph_blocks >= 3:
        conceptual_signals += 1
    if diversity <= 2:
        conceptual_signals += 1
    if not enumeratable:
        conceptual_signals += 1
    if stats.get("avg_paragraph_length", 0) >= 40:
        conceptual_signals += 1

    if reference_signals >= 3 and conceptual_signals <= 1:
        interpretation = "Reference-leaning"
    elif reference_signals >= 2 and conceptual_signals >= 2 or reference_signals >= 2:
        interpretation = "Mixed Usage"
    else:
        interpretation = "Conceptual Summary-leaning"

    return {
        "type": interpretation,
        "signals": {
            "reference": reference_signals,
            "conceptual": conceptual_signals,
            "structural_diversity": diversity,
            "enumeratable": enumeratable,
        },
    }


def _interpretation_rule_hints() -> dict:
    return {
        "reference_leaning": [
            "faq_present",
            "lists_tables",
            "entity_explanations",
        ],
        "conceptual_summary_leaning": [
            "long_narrative",
            "low_diversity",
            "few_units",
        ],
    }


def _blocker_signal_mapping(components: dict, stats: dict, entities_count: int, meta: dict, headings: list[dict]) -> dict:
    list_blocks = components.get("list_blocks", 0)
    table_blocks = components.get("table_blocks", 0)
    diversity = _structural_diversity(components)
    meta_description_empty = not meta.get("description")
    has_h1_h2 = any(h.get("level") in {"h1", "h2"} for h in headings)

    return {
        "no_enumeratable_facts": {
            "signals": ["ul_ol_count < threshold", "table_count == 0", "numeric_statements_ratio low"],
            "triggered": list_blocks == 0 and table_blocks == 0,
        },
        "weak_narrative_entry": {
            "signals": ["no_h1_or_h2", "meta_description_empty"],
            "triggered": (not has_h1_h2) or meta_description_empty,
        },
        "low_structural_diversity": {
            "signals": ["structural_diversity <= 2"],
            "triggered": diversity <= 2,
        },
    }


def _structural_fixes(blockers: list[str]) -> list[dict]:
    fixes = []
    if "no_enumeratable_facts" in blockers:
        fixes.append(
            {
                "action": "add_fact_list",
                "addresses_blockers": ["no_enumeratable_facts", "low_structural_diversity"],
            }
        )
    if "weak_narrative_entry" in blockers:
        fixes.append(
            {
                "action": "add_h_framing",
                "addresses_blockers": ["weak_narrative_entry"],
            }
        )
    return fixes


def _count_numeric_statements(paragraphs: list[str]) -> int:
    return sum(1 for text in paragraphs if any(char.isdigit() for char in text))


# Q&A pattern detection (Phase 2)
_QA_PATTERNS = [
    re.compile(r"^(what|how|why|when|where|who|which|can|does|is|are|do|will|should)\s+.+\?", re.IGNORECASE),
    re.compile(r"^.+\?\s*$"),  # Any sentence ending with ?
]


def _detect_qa_structure(headings: list[dict], paragraphs: list[str]) -> dict:
    """Detect Q&A patterns in headings and content."""
    question_headings = []
    question_paragraphs = []

    for h in headings:
        text = h.get("text", "")
        if any(p.search(text) for p in _QA_PATTERNS):
            question_headings.append(text)

    for p in paragraphs[:20]:  # Check first 20 paragraphs
        if any(pattern.search(p) for pattern in _QA_PATTERNS):
            question_paragraphs.append(p)

    has_qa_structure = len(question_headings) >= 2 or len(question_paragraphs) >= 3
    return {
        "has_qa_structure": has_qa_structure,
        "question_headings": len(question_headings),
        "question_paragraphs": len(question_paragraphs),
    }


def _assess_link_quality(parsed: dict) -> dict:
    """Assess internal and external link quality."""
    links = parsed.get("content", {}).get("links", [])
    if not links:
        return {
            "total_links": 0,
            "internal_links": 0,
            "external_links": 0,
            "descriptive_anchors": 0,
            "quality_score": 0,
        }

    internal = 0
    external = 0
    descriptive = 0

    # Generic anchor texts that are not descriptive
    generic_anchors = {"click here", "here", "link", "read more", "more", "learn more", "this"}

    for link in links:
        href = link.get("href", "")
        text = link.get("text", "").lower().strip()

        # Classify link type
        if href.startswith("/") or href.startswith("#"):
            internal += 1
        elif href.startswith("http"):
            external += 1
        else:
            internal += 1  # Relative links

        # Check anchor text quality
        if text and text not in generic_anchors and len(text) > 3:
            descriptive += 1

    total = len(links)
    # Quality score: balance of links with descriptive anchors
    quality_score = 0
    if total > 0:
        descriptive_ratio = descriptive / total
        if descriptive_ratio >= 0.8:
            quality_score = 3
        elif descriptive_ratio >= 0.5:
            quality_score = 2
        elif descriptive_ratio >= 0.3:
            quality_score = 1

    return {
        "total_links": total,
        "internal_links": internal,
        "external_links": external,
        "descriptive_anchors": descriptive,
        "quality_score": quality_score,
    }


def _assess_content_depth(parsed: dict) -> dict:
    """Assess content depth indicators."""
    stats = parsed.get("stats", {})
    content = parsed.get("content", {})
    headings = content.get("headings", [])

    word_count = stats.get("word_count", 0)

    # Count heading levels to assess section depth
    levels = [h.get("level", "h1") for h in headings]
    unique_levels = len(set(levels))
    has_deep_hierarchy = unique_levels >= 3  # h1, h2, h3+

    # Depth score based on word count and structure
    depth_score = 0

    # Word count component (0-3 points)
    if word_count >= 2000:
        depth_score += 3
    elif word_count >= 1000:
        depth_score += 2
    elif word_count >= 500:
        depth_score += 1

    # Heading hierarchy depth (0-2 points)
    if has_deep_hierarchy:
        depth_score += 2
    elif unique_levels >= 2:
        depth_score += 1

    return {
        "word_count": word_count,
        "unique_heading_levels": unique_levels,
        "has_deep_hierarchy": has_deep_hierarchy,
        "depth_score": depth_score,
    }


# Phase 3: Advanced features

# Unclear pronouns that may confuse AI when taken out of context
_UNCLEAR_PRONOUNS = re.compile(
    r"\b(this|that|these|those|it|they|them|he|she|him|her)\b",
    re.IGNORECASE
)

# Strong opening patterns that help AI understand content quickly
_STRONG_OPENING_PATTERNS = [
    re.compile(r"^.+\s+(is|are|was|were)\s+.+", re.IGNORECASE),  # Definition-style
    re.compile(r"^(this|the)\s+(article|guide|post|tutorial|page)\s+", re.IGNORECASE),  # Meta-description
    re.compile(r"^(learn|discover|find out|understand)\s+", re.IGNORECASE),  # Action-oriented
    re.compile(r"^\d+\s+.+", re.IGNORECASE),  # Numbered fact
]


def _assess_first_paragraph(paragraphs: list[str]) -> dict:
    """Assess if the first paragraph serves as a good summary for AI."""
    if not paragraphs:
        return {
            "has_strong_opening": False,
            "first_paragraph_length": 0,
            "score": 0,
        }

    first_para = paragraphs[0].strip()
    word_count = len(first_para.split())

    # Check for strong opening patterns
    has_strong_opening = any(p.search(first_para) for p in _STRONG_OPENING_PATTERNS)

    # Ideal first paragraph: 50-200 words, serves as summary
    score = 0
    if 50 <= word_count <= 200:
        score += 2
    elif 30 <= word_count <= 250:
        score += 1

    if has_strong_opening:
        score += 1

    return {
        "has_strong_opening": has_strong_opening,
        "first_paragraph_length": word_count,
        "score": score,
    }


def _detect_pronoun_issues(paragraphs: list[str]) -> dict:
    """Detect paragraphs starting with unclear pronouns (problematic for AI citation)."""
    problematic_starts = []
    total_pronoun_count = 0

    for i, para in enumerate(paragraphs[:10]):  # Check first 10 paragraphs
        para = para.strip()
        if not para:
            continue

        # Check if paragraph starts with unclear pronoun
        first_word = para.split()[0] if para else ""
        if first_word.lower() in {"this", "that", "these", "those", "it", "they", "he", "she"}:
            problematic_starts.append(i)

        # Count total pronouns
        total_pronoun_count += len(_UNCLEAR_PRONOUNS.findall(para))

    # Score: fewer problematic starts = better
    score = 0
    if len(problematic_starts) == 0:
        score = 2
    elif len(problematic_starts) <= 2:
        score = 1

    return {
        "paragraphs_starting_with_pronoun": len(problematic_starts),
        "total_pronouns_in_first_10": total_pronoun_count,
        "score": score,
    }


def _calculate_citation_potential(parsed: dict, qa_structure: dict, link_quality: dict) -> dict:
    """
    Estimate how likely AI systems will cite this content.
    Based on: quotability, authority signals, and structural clarity.
    """
    quotable = parsed.get("quotable_sentences", [])
    schema_org = parsed.get("schema_org", {})
    entities = parsed.get("entities", [])

    score = 0
    signals = []

    # Quotable content (0-3 points)
    if len(quotable) >= 3:
        score += 3
        signals.append("multiple_quotable_sentences")
    elif len(quotable) >= 1:
        score += 1
        signals.append("has_quotable_content")

    # Authority signals (0-2 points)
    if schema_org.get("has_article"):
        score += 1
        signals.append("article_schema")
    if schema_org.get("has_faq"):
        score += 1
        signals.append("faq_schema")

    # Entity richness (0-2 points) - specific facts are more citable
    if len(entities) >= 5:
        score += 2
        signals.append("entity_rich")
    elif len(entities) >= 2:
        score += 1
        signals.append("has_entities")

    # Q&A structure (0-2 points) - clear Q&A is highly citable
    if qa_structure.get("has_qa_structure"):
        score += 2
        signals.append("qa_structure")

    # Link quality (0-1 point) - good references add credibility
    if link_quality.get("external_links", 0) >= 2:
        score += 1
        signals.append("external_references")

    # Determine potential level
    if score >= 8:
        level = "high"
    elif score >= 5:
        level = "medium"
    elif score >= 2:
        level = "low"
    else:
        level = "minimal"

    return {
        "score": score,
        "max_score": 11,
        "level": level,
        "signals": signals,
    }


# === GEO Score Component Functions ===


def _score_accessibility(ai_access: dict, blockers: list[str]) -> int:
    """
    Calculate accessibility score (0-40 points).
    Measures how accessible content is to AI crawlers.
    """
    score = 40  # Start with full points

    # Check AI crawler access (-10 per blocked crawler)
    crawler_statuses = [
        ai_access.get("gptbot"),
        ai_access.get("claudebot"),
        ai_access.get("perplexitybot"),
        ai_access.get("google_extended"),
    ]
    blocked_count = sum(1 for s in crawler_statuses if s == "disallow")
    score -= blocked_count * 10

    # Check meta robots / X-Robots-Tag
    meta_robots = ai_access.get("meta_robots", {})
    x_robots = ai_access.get("x_robots_tag", {})
    if meta_robots.get("noindex") or x_robots.get("noindex"):
        score -= 15
    if meta_robots.get("nofollow") or x_robots.get("nofollow"):
        score -= 5

    # Deduct for blockers
    score -= len(blockers) * 5

    return max(0, score)


def _score_structure(parsed: dict, qa_structure: dict) -> int:
    """
    Calculate structure score (0-30 points).
    Measures how well content is structured for AI comprehension.
    """
    score = 0
    components = parsed.get("content_surface_size", {}).get("components", {})
    stats = parsed.get("stats", {})
    schema_org = parsed.get("schema_org", {})

    # Heading hierarchy (0-8 points)
    heading_count = stats.get("heading_count", 0)
    if heading_count >= 5:
        score += 8
    elif heading_count >= 3:
        score += 6
    elif heading_count >= 1:
        score += 4

    # Lists and tables (0-7 points)
    list_blocks = components.get("list_blocks", 0)
    table_blocks = components.get("table_blocks", 0)
    if list_blocks >= 2 or table_blocks >= 1:
        score += 7
    elif list_blocks >= 1 or table_blocks >= 1:
        score += 5

    # Schema.org structured data (0-11 points)
    if schema_org.get("available"):
        score += min(11, schema_org.get("score_contribution", 0))

    # Breadcrumb Schema bonus (0-2 points)
    if schema_org.get("has_breadcrumb"):
        score += 2

    # Q&A structure bonus (0-4 points)
    if qa_structure.get("has_qa_structure"):
        score += 4
    elif qa_structure.get("question_headings", 0) >= 1:
        score += 2

    return min(30, score)


def _score_quality(
    parsed: dict,
    link_quality: dict,
    content_depth: dict,
    first_paragraph: dict,
    pronoun_issues: dict,
) -> int:
    """
    Calculate quality score (0-30 points).
    Measures content quality for AI citation potential.
    """
    score = 0
    readability = parsed.get("readability", {})
    entities = parsed.get("entities", [])
    components = parsed.get("content_surface_size", {}).get("components", {})
    stats = parsed.get("stats", {})

    # Readability (0-6 points)
    if readability.get("available"):
        flesch = readability.get("flesch_reading_ease", 50)
        if flesch >= 60:
            score += 6
        elif flesch >= 50:
            score += 5
        elif flesch >= 40:
            score += 4
        elif flesch >= 30:
            score += 2
        else:
            score += 1
    else:
        score += 3  # Default when not available

    # Entity richness (0-4 points)
    entity_count = len(entities)
    if entity_count >= 10:
        score += 4
    elif entity_count >= 5:
        score += 3
    elif entity_count >= 2:
        score += 2
    elif entity_count >= 1:
        score += 1

    # Definition density (0-5 points)
    definition_blocks = components.get("definition_blocks", 0)
    if definition_blocks >= 3:
        score += 5
    elif definition_blocks >= 2:
        score += 4
    elif definition_blocks >= 1:
        score += 2

    # Content ratio (0-4 points)
    content_ratio = stats.get("content_ratio", 0.5)
    if content_ratio >= 0.7:
        score += 4
    elif content_ratio >= 0.5:
        score += 3
    elif content_ratio >= 0.3:
        score += 2

    # Quotable sentences with type diversity (0-5 points)
    quotable = parsed.get("quotable_sentences", [])
    quotable_count = len(quotable)
    quotable_types = {q.get("type", "unknown") for q in quotable}
    high_value_types = {"statistic", "citation"}
    has_high_value = bool(quotable_types & high_value_types)

    if quotable_count >= 3 and len(quotable_types) >= 2:
        score += 5
    elif quotable_count >= 2 and has_high_value:
        score += 4
    elif quotable_count >= 3 or (quotable_count >= 1 and has_high_value):
        score += 3
    elif quotable_count >= 1:
        score += 2

    # Link quality (0-2 points)
    score += min(2, link_quality.get("quality_score", 0))

    # Content depth (0-2 points)
    score += min(2, content_depth.get("depth_score", 0))

    # First paragraph quality (0-2 points)
    score += min(2, first_paragraph.get("score", 0))

    # Pronoun clarity (0-2 points)
    score += pronoun_issues.get("score", 0)

    return min(30, score)


def _determine_grade(total_score: int) -> tuple[str, str]:
    """Determine letter grade and label from total score."""
    if total_score >= 90:
        return "A", "excellent"
    elif total_score >= 75:
        return "B", "good"
    elif total_score >= 60:
        return "C", "fair"
    elif total_score >= 40:
        return "D", "poor"
    else:
        return "F", "critical"


def _calculate_geo_score(parsed: dict, ai_access: dict, blockers: list[str]) -> dict:
    """
    Calculate weighted GEO Score (0-100) based on three dimensions:
    - Accessibility (40%): AI crawler access, blockers
    - Structure (30%): Heading hierarchy, lists/tables, Schema.org, Q&A structure
    - Quality (30%): Readability, definitions, content ratio, entity richness, link quality
    """
    # Pre-compute metrics needed by multiple scorers
    content = parsed.get("content", {})
    headings = content.get("headings", [])
    paragraphs = content.get("paragraphs", [])

    qa_structure = _detect_qa_structure(headings, paragraphs)
    link_quality = _assess_link_quality(parsed)
    content_depth = _assess_content_depth(parsed)
    first_paragraph = _assess_first_paragraph(paragraphs)
    pronoun_issues = _detect_pronoun_issues(paragraphs)

    # Calculate component scores using dedicated functions
    accessibility_score = _score_accessibility(ai_access, blockers)
    structure_score = _score_structure(parsed, qa_structure)
    quality_score = _score_quality(
        parsed, link_quality, content_depth, first_paragraph, pronoun_issues
    )

    # Calculate total and determine grade
    total_score = accessibility_score + structure_score + quality_score
    total_score = max(0, min(100, total_score))
    grade, grade_label = _determine_grade(total_score)

    return {
        "total": total_score,
        "grade": grade,
        "grade_label": grade_label,
        "breakdown": {
            "accessibility": {
                "score": accessibility_score,
                "max": 40,
                "percentage": round(accessibility_score / 40 * 100),
            },
            "structure": {
                "score": structure_score,
                "max": 30,
                "percentage": round(structure_score / 30 * 100),
            },
            "quality": {
                "score": quality_score,
                "max": 30,
                "percentage": round(quality_score / 30 * 100),
            },
        },
    }


def _generate_summary(geo_score: dict, blockers: list[str], ai_access: dict, parsed: dict, draft_mode: bool = False) -> dict:
    """Generate a human-readable summary with priority recommendations."""
    issues = {
        "critical": [],
        "warning": [],
        "good": [],
    }

    if not draft_mode:
        # Check critical issues (skip in draft mode)
        crawler_statuses = [
            ai_access.get("gptbot"),
            ai_access.get("claudebot"),
            ai_access.get("perplexitybot"),
            ai_access.get("google_extended"),
        ]
        blocked_crawlers = [name for name, status in zip(
            ["GPTBot", "ClaudeBot", "PerplexityBot", "Google-Extended"],
            crawler_statuses
        ) if status == "disallow"]

        if blocked_crawlers:
            issues["critical"].append({
                "key": "crawlers_blocked",
                "crawlers": blocked_crawlers,
            })

        meta_robots = ai_access.get("meta_robots", {})
        if meta_robots.get("noindex"):
            issues["critical"].append({"key": "noindex_set"})

    # Check warnings
    schema_org = parsed.get("schema_org", {})
    if not schema_org.get("available") or not schema_org.get("types_found"):
        issues["warning"].append({"key": "no_schema"})

    if "weak_narrative_entry" in blockers:
        issues["warning"].append({"key": "weak_entry"})

    if "no_enumeratable_facts" in blockers:
        issues["warning"].append({"key": "no_facts"})

    readability = parsed.get("readability", {})
    if readability.get("available") and readability.get("flesch_reading_ease", 100) < 40:
        issues["warning"].append({"key": "low_readability"})

    # Check content depth
    stats = parsed.get("stats", {})
    word_count = stats.get("word_count", 0)
    if word_count < 300:
        issues["warning"].append({"key": "thin_content"})

    # Check good practices
    if schema_org.get("has_faq"):
        issues["good"].append({"key": "has_faq_schema"})

    if schema_org.get("has_article"):
        issues["good"].append({"key": "has_article_schema"})

    if schema_org.get("has_breadcrumb"):
        issues["good"].append({"key": "has_breadcrumb_schema"})

    components = parsed.get("content_surface_size", {}).get("components", {})
    if components.get("list_blocks", 0) >= 2:
        issues["good"].append({"key": "good_lists"})

    if components.get("definition_blocks", 0) >= 2:
        issues["good"].append({"key": "good_definitions"})

    # Entity richness check
    entities = parsed.get("entities", [])
    if len(entities) >= 5:
        issues["good"].append({"key": "entity_rich"})

    quotable = parsed.get("quotable_sentences", [])
    quotable_types = {q.get("type", "unknown") for q in quotable}
    if len(quotable) >= 2:
        issues["good"].append({"key": "quotable_content"})
    if len(quotable_types) >= 2:
        issues["good"].append({"key": "quotable_diversity"})

    # Phase 2: Q&A structure good practice
    content = parsed.get("content", {})
    headings = content.get("headings", [])
    paragraphs = content.get("paragraphs", [])
    qa_structure = _detect_qa_structure(headings, paragraphs)
    if qa_structure.get("has_qa_structure"):
        issues["good"].append({"key": "qa_structure"})

    # Phase 2: Content depth good practice
    if word_count >= 1000:
        issues["good"].append({"key": "comprehensive_content"})

    # Phase 3: First paragraph assessment
    first_paragraph = _assess_first_paragraph(paragraphs)
    if first_paragraph.get("has_strong_opening"):
        issues["good"].append({"key": "strong_opening"})
    elif first_paragraph.get("first_paragraph_length", 0) < 30:
        issues["warning"].append({"key": "weak_opening"})

    # Phase 3: Pronoun clarity
    pronoun_issues = _detect_pronoun_issues(paragraphs)
    if pronoun_issues.get("paragraphs_starting_with_pronoun", 0) >= 3:
        issues["warning"].append({"key": "unclear_pronouns"})
    elif pronoun_issues.get("score", 0) >= 2:
        issues["good"].append({"key": "clear_pronouns"})

    # Phase 3: Citation potential
    link_quality = _assess_link_quality(parsed)
    citation_potential = _calculate_citation_potential(parsed, qa_structure, link_quality)
    if citation_potential.get("level") == "high":
        issues["good"].append({"key": "high_citation_potential"})

    # Generate one-line summary
    grade = geo_score.get("grade", "C")
    if grade == "A":
        summary_key = "summary_excellent"
    elif grade == "B":
        summary_key = "summary_good"
    elif grade == "C":
        summary_key = "summary_fair"
    else:
        summary_key = "summary_poor"

    return {
        "summary_key": summary_key,
        "issues": issues,
        "priority_fixes": _get_priority_fixes(issues, blockers, parsed),
    }


def _get_priority_fixes(issues: dict, blockers: list[str], parsed: dict) -> list[dict]:
    """Get prioritized list of recommended fixes."""
    fixes = []

    # Critical fixes first
    for issue in issues.get("critical", []):
        if issue.get("key") == "crawlers_blocked":
            fixes.append({
                "priority": "critical",
                "action": "update_robots_txt",
                "impact": "high",
            })
        elif issue.get("key") == "noindex_set":
            fixes.append({
                "priority": "critical",
                "action": "remove_noindex",
                "impact": "high",
            })

    # Warning fixes
    for issue in issues.get("warning", []):
        if issue.get("key") == "no_schema":
            fixes.append({
                "priority": "recommended",
                "action": "add_schema",
                "impact": "medium",
            })
        elif issue.get("key") == "weak_entry":
            fixes.append({
                "priority": "recommended",
                "action": "add_h_framing",
                "impact": "medium",
            })
        elif issue.get("key") == "no_facts":
            fixes.append({
                "priority": "recommended",
                "action": "add_fact_list",
                "impact": "medium",
            })
        elif issue.get("key") == "low_readability":
            fixes.append({
                "priority": "suggested",
                "action": "improve_readability",
                "impact": "low",
            })
        elif issue.get("key") == "thin_content":
            fixes.append({
                "priority": "recommended",
                "action": "expand_content",
                "impact": "medium",
            })
        elif issue.get("key") == "weak_opening":
            fixes.append({
                "priority": "suggested",
                "action": "improve_first_paragraph",
                "impact": "medium",
            })
        elif issue.get("key") == "unclear_pronouns":
            fixes.append({
                "priority": "suggested",
                "action": "reduce_pronouns",
                "impact": "low",
            })

    return fixes[:5]  # Return top 5 fixes


def check_geo(parsed: dict, html: str, url: str, *, draft_mode: bool = False) -> dict:
    """Run v2.1.0 GEO checks with weighted scoring and extended metrics.

    Args:
        draft_mode: When True, skip accessibility checks (robots.txt, noindex).
                    Used for Ghost draft analysis where these metrics are irrelevant.
    """
    components = parsed.get("content_surface_size", {}).get("components", {})
    stats = parsed.get("stats", {}).copy()
    content = parsed.get("content", {})
    paragraphs = content.get("paragraphs", [])
    headings = content.get("headings", [])
    entities = parsed.get("entities", [])

    stats["numeric_statements"] = _count_numeric_statements(paragraphs)

    interpretation = _interpretation_type(components, stats, len(entities))
    mapping = _blocker_signal_mapping(components, stats, len(entities), parsed.get("meta", {}), headings)
    blockers = [name for name, data in mapping.items() if data.get("triggered")]

    # Phase 2: Compute extended metrics
    qa_structure = _detect_qa_structure(headings, paragraphs)
    link_quality = _assess_link_quality(parsed)
    content_depth = _assess_content_depth(parsed)

    if draft_mode:
        # Draft mode: skip accessibility, give full marks
        ai_access = _draft_mode_ai_access()
        geo_score = _calculate_geo_score(parsed, ai_access, blockers=[])
        summary = _generate_summary(geo_score, blockers, ai_access, parsed, draft_mode=True)
    else:
        ai_access = _ai_crawler_access(url, html)
        geo_score = _calculate_geo_score(parsed, ai_access, blockers)
        summary = _generate_summary(geo_score, blockers, ai_access, parsed)

    # Phase 3: Compute advanced metrics
    first_paragraph = _assess_first_paragraph(paragraphs)
    pronoun_issues = _detect_pronoun_issues(paragraphs)
    citation_potential = _calculate_citation_potential(parsed, qa_structure, link_quality)

    result = {
        "geo_score": geo_score,
        "summary": summary,
        "ai_crawler_access": ai_access,
        "ai_usage_interpretation": interpretation,
        "interpretation_rule_hints": _interpretation_rule_hints(),
        "last_mile_blockers": blockers,
        "blocker_signal_mapping": mapping,
        "structural_fixes": _structural_fixes(blockers),
        # Phase 2 & 3: Extended metrics
        "extended_metrics": {
            "qa_structure": qa_structure,
            "link_quality": link_quality,
            "content_depth": content_depth,
            "entity_count": len(entities),
            # Phase 3
            "first_paragraph": first_paragraph,
            "pronoun_clarity": pronoun_issues,
            "citation_potential": citation_potential,
        },
    }

    if draft_mode:
        result["draft_mode"] = True

    return result
