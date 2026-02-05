"""Unit tests for SEO checker module."""
from __future__ import annotations

from src.seo.seo_checker import (
    Severity,
    _check_canonical,
    _check_description,
    _check_headings,
    _check_title,
    check_seo,
)


class TestTitleChecks:
    """Tests for title tag validation."""

    def test_missing_title(self):
        """Title missing should return error."""
        meta = {"title": ""}
        issues = _check_title(meta)
        assert len(issues) == 1
        assert issues[0].rule_id == "title_missing"
        assert issues[0].severity == Severity.ERROR

    def test_title_too_short(self):
        """Short title should return warning."""
        meta = {"title": "Short"}
        issues = _check_title(meta)
        assert len(issues) == 1
        assert issues[0].rule_id == "title_too_short"
        assert issues[0].severity == Severity.WARNING

    def test_title_too_long(self):
        """Long title should return warning."""
        meta = {"title": "A" * 70}
        issues = _check_title(meta)
        assert len(issues) == 1
        assert issues[0].rule_id == "title_too_long"
        assert issues[0].severity == Severity.WARNING

    def test_title_optimal_length(self):
        """Optimal title length should return no issues."""
        meta = {"title": "This is a good title that is about 55 characters long."}
        issues = _check_title(meta)
        assert len(issues) == 0


class TestDescriptionChecks:
    """Tests for meta description validation."""

    def test_missing_description(self):
        """Missing description should return warning."""
        meta = {"description": ""}
        issues = _check_description(meta)
        assert len(issues) == 1
        assert issues[0].rule_id == "description_missing"
        assert issues[0].severity == Severity.WARNING

    def test_description_too_short(self):
        """Short description should return info."""
        meta = {"description": "Too short."}
        issues = _check_description(meta)
        assert len(issues) == 1
        assert issues[0].rule_id == "description_too_short"
        assert issues[0].severity == Severity.INFO

    def test_description_too_long(self):
        """Long description should return info."""
        meta = {"description": "A" * 200}
        issues = _check_description(meta)
        assert len(issues) == 1
        assert issues[0].rule_id == "description_too_long"
        assert issues[0].severity == Severity.INFO

    def test_description_optimal_length(self):
        """Optimal description length should return no issues."""
        meta = {"description": "This is a comprehensive meta description that provides a good summary of the page content. It is between 120 and 160 characters."}
        issues = _check_description(meta)
        assert len(issues) == 0


class TestHeadingChecks:
    """Tests for heading structure validation."""

    def test_no_h1(self):
        """Missing H1 should return warning."""
        parsed = {"content": {"headings": [{"level": "h2", "text": "Subheading"}]}}
        issues = _check_headings(parsed)
        assert any(i.rule_id == "h1_missing" for i in issues)

    def test_multiple_h1(self):
        """Multiple H1s should return warning."""
        parsed = {"content": {"headings": [
            {"level": "h1", "text": "First"},
            {"level": "h1", "text": "Second"},
        ]}}
        issues = _check_headings(parsed)
        assert any(i.rule_id == "multiple_h1" for i in issues)

    def test_single_h1(self):
        """Single H1 should not trigger h1 issues."""
        parsed = {"content": {"headings": [
            {"level": "h1", "text": "Main Heading"},
            {"level": "h2", "text": "Subheading"},
        ]}}
        issues = _check_headings(parsed)
        h1_issues = [i for i in issues if i.rule_id in ("h1_missing", "multiple_h1")]
        assert len(h1_issues) == 0

    def test_empty_heading(self):
        """Empty heading should return warning."""
        parsed = {"content": {"headings": [
            {"level": "h1", "text": ""},
        ]}}
        issues = _check_headings(parsed)
        assert any(i.rule_id == "empty_headings" for i in issues)

    def test_heading_skip(self):
        """Skipped heading level should return info."""
        parsed = {"content": {"headings": [
            {"level": "h1", "text": "Main"},
            {"level": "h3", "text": "Skipped H2"},  # Skips h2
        ]}}
        issues = _check_headings(parsed)
        assert any(i.rule_id == "heading_skip" for i in issues)


class TestCanonicalChecks:
    """Tests for canonical URL validation."""

    def test_missing_canonical(self):
        """Missing canonical should return info."""
        meta = {"canonical": ""}
        issues = _check_canonical(meta, "https://example.com")
        assert len(issues) == 1
        assert issues[0].rule_id == "canonical_missing"
        assert issues[0].severity == Severity.INFO

    def test_valid_canonical(self):
        """Valid canonical should return no issues."""
        meta = {"canonical": "https://example.com/page"}
        issues = _check_canonical(meta, "https://example.com/page")
        assert len(issues) == 0

    def test_invalid_canonical(self):
        """Invalid canonical should return warning."""
        meta = {"canonical": "/relative-path"}
        issues = _check_canonical(meta, "https://example.com")
        assert len(issues) == 1
        assert issues[0].rule_id == "canonical_invalid"


class TestFullSEOCheck:
    """Integration tests for full SEO check."""

    def test_check_seo_returns_list(self, valid_html: str, parsed_content: dict):
        """check_seo should return a list of dicts."""
        result = check_seo(parsed_content, valid_html)
        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, dict)
            assert "rule_id" in item
            assert "severity" in item
            assert "message" in item

    def test_check_seo_sorted_by_severity(self, html_noindex: str):
        """Issues should be sorted by severity (errors first)."""
        from src.parser.content_parser import parse_content
        parsed = parse_content(html_noindex, "https://example.com")
        result = check_seo(parsed, html_noindex)

        # Find severity positions
        severities = [r["severity"] for r in result]
        error_positions = [i for i, s in enumerate(severities) if s == "error"]
        warning_positions = [i for i, s in enumerate(severities) if s == "warning"]
        info_positions = [i for i, s in enumerate(severities) if s == "info"]

        # Errors should come before warnings, warnings before info
        if error_positions and warning_positions:
            assert max(error_positions) < min(warning_positions)
        if warning_positions and info_positions:
            assert max(warning_positions) < min(info_positions)
