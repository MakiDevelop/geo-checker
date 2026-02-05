"""SEO rule checks."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from urllib.parse import urlparse

from bs4 import BeautifulSoup


class Severity(Enum):
    """Issue severity levels."""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class SEOIssue:
    """Represents an SEO issue found during analysis."""
    rule_id: str
    severity: Severity
    message: str
    element: str | None = None
    suggestion: str | None = None
    current_value: str | None = None
    recommended_value: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


# SEO rule thresholds
TITLE_MIN_LENGTH = 30
TITLE_MAX_LENGTH = 60
TITLE_OPTIMAL_MIN = 50
TITLE_OPTIMAL_MAX = 60

DESCRIPTION_MIN_LENGTH = 70
DESCRIPTION_MAX_LENGTH = 160
DESCRIPTION_OPTIMAL_MIN = 120
DESCRIPTION_OPTIMAL_MAX = 160


def _check_title(meta: dict) -> list[SEOIssue]:
    """Check page title for SEO best practices."""
    issues = []
    title = meta.get("title", "")

    if not title:
        issues.append(SEOIssue(
            rule_id="title_missing",
            severity=Severity.ERROR,
            message="Page title is missing",
            suggestion="Add a descriptive <title> tag to the page",
        ))
        return issues

    title_length = len(title)

    if title_length < TITLE_MIN_LENGTH:
        issues.append(SEOIssue(
            rule_id="title_too_short",
            severity=Severity.WARNING,
            message=f"Title is too short ({title_length} chars)",
            current_value=str(title_length),
            recommended_value=f"{TITLE_OPTIMAL_MIN}-{TITLE_OPTIMAL_MAX}",
            suggestion="Expand the title to be more descriptive (50-60 characters recommended)",
        ))
    elif title_length > TITLE_MAX_LENGTH:
        issues.append(SEOIssue(
            rule_id="title_too_long",
            severity=Severity.WARNING,
            message=f"Title may be truncated in search results ({title_length} chars)",
            current_value=str(title_length),
            recommended_value=f"{TITLE_OPTIMAL_MIN}-{TITLE_OPTIMAL_MAX}",
            suggestion="Shorten the title to prevent truncation (50-60 characters recommended)",
        ))

    return issues


def _check_description(meta: dict) -> list[SEOIssue]:
    """Check meta description for SEO best practices."""
    issues = []
    description = meta.get("description", "")

    if not description:
        issues.append(SEOIssue(
            rule_id="description_missing",
            severity=Severity.WARNING,
            message="Meta description is missing",
            suggestion="Add a meta description to improve click-through rates",
        ))
        return issues

    desc_length = len(description)

    if desc_length < DESCRIPTION_MIN_LENGTH:
        issues.append(SEOIssue(
            rule_id="description_too_short",
            severity=Severity.INFO,
            message=f"Meta description is short ({desc_length} chars)",
            current_value=str(desc_length),
            recommended_value=f"{DESCRIPTION_OPTIMAL_MIN}-{DESCRIPTION_OPTIMAL_MAX}",
            suggestion="Expand the description for better search visibility (120-160 characters recommended)",
        ))
    elif desc_length > DESCRIPTION_MAX_LENGTH:
        issues.append(SEOIssue(
            rule_id="description_too_long",
            severity=Severity.INFO,
            message=f"Meta description may be truncated ({desc_length} chars)",
            current_value=str(desc_length),
            recommended_value=f"{DESCRIPTION_OPTIMAL_MIN}-{DESCRIPTION_OPTIMAL_MAX}",
            suggestion="Shorten the description to prevent truncation (120-160 characters recommended)",
        ))

    return issues


def _check_headings(parsed: dict) -> list[SEOIssue]:
    """Check heading structure for SEO best practices."""
    issues = []
    headings = parsed.get("content", {}).get("headings", [])

    # Count H1 tags
    h1_headings = [h for h in headings if h.get("level") == "h1"]
    h1_count = len(h1_headings)

    if h1_count == 0:
        issues.append(SEOIssue(
            rule_id="h1_missing",
            severity=Severity.WARNING,
            message="No H1 heading found on the page",
            suggestion="Add a single H1 heading that describes the page content",
        ))
    elif h1_count > 1:
        issues.append(SEOIssue(
            rule_id="multiple_h1",
            severity=Severity.WARNING,
            message=f"Multiple H1 headings found ({h1_count})",
            current_value=str(h1_count),
            recommended_value="1",
            suggestion="Use only one H1 per page for better SEO structure",
        ))

    # Check for empty headings
    empty_headings = [h for h in headings if not h.get("text", "").strip()]
    if empty_headings:
        issues.append(SEOIssue(
            rule_id="empty_headings",
            severity=Severity.WARNING,
            message=f"Found {len(empty_headings)} empty heading(s)",
            suggestion="Remove or fill in empty heading tags",
        ))

    # Check heading hierarchy
    if headings:
        levels = [h.get("level", "") for h in headings if h.get("level")]
        level_order = ["h1", "h2", "h3", "h4", "h5", "h6"]

        for i, level in enumerate(levels[:-1]):
            current_idx = level_order.index(level) if level in level_order else -1
            next_level = levels[i + 1]
            next_idx = level_order.index(next_level) if next_level in level_order else -1

            if current_idx >= 0 and next_idx >= 0 and next_idx > current_idx + 1:
                issues.append(SEOIssue(
                    rule_id="heading_skip",
                    severity=Severity.INFO,
                    message=f"Heading level skipped: {level} followed by {next_level}",
                    suggestion="Maintain proper heading hierarchy (don't skip levels)",
                ))
                break  # Report only first occurrence

    return issues


def _check_canonical(meta: dict, url: str) -> list[SEOIssue]:
    """Check canonical URL configuration."""
    issues = []
    canonical = meta.get("canonical", "")

    if not canonical:
        issues.append(SEOIssue(
            rule_id="canonical_missing",
            severity=Severity.INFO,
            message="No canonical URL specified",
            suggestion="Add a canonical URL to prevent duplicate content issues",
        ))
        return issues

    # Check if canonical is valid URL
    parsed_canonical = urlparse(canonical)
    if not parsed_canonical.scheme or not parsed_canonical.netloc:
        issues.append(SEOIssue(
            rule_id="canonical_invalid",
            severity=Severity.WARNING,
            message="Canonical URL appears to be invalid",
            current_value=canonical,
            suggestion="Use a fully qualified URL for the canonical tag",
        ))

    return issues


def _check_images(html: str) -> list[SEOIssue]:
    """Check images for alt text and other SEO attributes."""
    issues = []
    soup = BeautifulSoup(html, "lxml")
    images = soup.find_all("img")

    if not images:
        return issues

    missing_alt = []
    empty_alt = []

    for img in images:
        src = img.get("src", "")
        alt = img.get("alt")

        # Skip tracking pixels and tiny images
        if "pixel" in src.lower() or "1x1" in src:
            continue

        if alt is None:
            missing_alt.append(src[:50])
        elif alt.strip() == "":
            empty_alt.append(src[:50])

    if missing_alt:
        issues.append(SEOIssue(
            rule_id="images_missing_alt",
            severity=Severity.WARNING,
            message=f"{len(missing_alt)} image(s) missing alt attribute",
            current_value=str(len(missing_alt)),
            suggestion="Add descriptive alt text to all meaningful images",
        ))

    if empty_alt:
        issues.append(SEOIssue(
            rule_id="images_empty_alt",
            severity=Severity.INFO,
            message=f"{len(empty_alt)} image(s) have empty alt attribute",
            current_value=str(len(empty_alt)),
            suggestion="Add descriptive alt text unless image is decorative",
        ))

    return issues


def _check_links(parsed: dict) -> list[SEOIssue]:
    """Check links for SEO issues."""
    issues = []
    links = parsed.get("links", {})

    internal = links.get("internal", [])
    external = links.get("external", [])

    # Check for too many external links
    if len(external) > 100:
        issues.append(SEOIssue(
            rule_id="too_many_external_links",
            severity=Severity.INFO,
            message=f"Page has many external links ({len(external)})",
            current_value=str(len(external)),
            suggestion="Consider reducing external links or using nofollow where appropriate",
        ))

    # Check for broken internal link patterns (common issues)
    for link in internal[:50]:  # Check first 50
        href = link.get("href", "")
        if href.startswith("javascript:") or href == "#":
            continue
        if "undefined" in href or "null" in href:
            issues.append(SEOIssue(
                rule_id="suspicious_link",
                severity=Severity.WARNING,
                message="Found potentially broken link pattern",
                current_value=href[:100],
                suggestion="Review and fix links containing 'undefined' or 'null'",
            ))
            break

    return issues


def _check_meta_robots(parsed: dict) -> list[SEOIssue]:
    """Check meta robots directives."""
    issues = []
    meta = parsed.get("meta", {})
    robots = meta.get("robots", "")

    if robots:
        robots_lower = robots.lower()
        if "noindex" in robots_lower:
            issues.append(SEOIssue(
                rule_id="noindex_detected",
                severity=Severity.ERROR,
                message="Page is set to noindex - it won't appear in search results",
                current_value=robots,
                suggestion="Remove noindex if you want the page to be indexed",
            ))
        if "nofollow" in robots_lower:
            issues.append(SEOIssue(
                rule_id="nofollow_detected",
                severity=Severity.WARNING,
                message="Page is set to nofollow - links won't pass PageRank",
                current_value=robots,
                suggestion="Remove nofollow if you want links to be followed",
            ))

    return issues


def _check_content_quality(parsed: dict) -> list[SEOIssue]:
    """Check content quality indicators."""
    issues = []
    stats = parsed.get("stats", {})

    word_count = stats.get("word_count", 0)
    if word_count < 300:
        issues.append(SEOIssue(
            rule_id="thin_content",
            severity=Severity.WARNING,
            message=f"Page has thin content ({word_count} words)",
            current_value=str(word_count),
            recommended_value="300+",
            suggestion="Add more substantive content for better search visibility",
        ))

    return issues


def check_seo(parsed: dict, html: str) -> list[dict]:
    """Run SEO checks on parsed content.

    Args:
        parsed: Parsed content dictionary from content_parser
        html: Raw HTML string

    Returns:
        List of SEO issues as dictionaries
    """
    issues: list[SEOIssue] = []
    meta = parsed.get("meta", {})
    url = parsed.get("url", "")

    # Run all checks
    issues.extend(_check_title(meta))
    issues.extend(_check_description(meta))
    issues.extend(_check_headings(parsed))
    issues.extend(_check_canonical(meta, url))
    issues.extend(_check_images(html))
    issues.extend(_check_links(parsed))
    issues.extend(_check_meta_robots(parsed))
    issues.extend(_check_content_quality(parsed))

    # Sort by severity (errors first, then warnings, then info)
    severity_order = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
    issues.sort(key=lambda x: severity_order.get(x.severity, 3))

    return [issue.to_dict() for issue in issues]
