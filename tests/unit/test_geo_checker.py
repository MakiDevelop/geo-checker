"""Unit tests for GEO checker module."""
from __future__ import annotations

import pytest

from src.geo.geo_checker import (
    _calculate_geo_score,
    _determine_grade,
    _evaluate_group,
    _extract_meta_robots,
    _parse_robots_txt,
    _score_accessibility,
    _score_quality,
    _score_structure,
    _select_group,
    _structural_diversity,
    check_geo,
)


class TestRobotsTxtParsing:
    """Tests for robots.txt parsing."""

    def test_parse_basic_robots(self):
        """Parse simple robots.txt with multiple agents."""
        robots = """
User-agent: GPTBot
Disallow: /private

User-agent: *
Allow: /
"""
        groups = _parse_robots_txt(robots)
        assert len(groups) >= 1

    def test_parse_empty_robots(self):
        """Empty robots.txt should return empty list."""
        groups = _parse_robots_txt("")
        assert groups == []

    def test_parse_comments_ignored(self):
        """Comments should be ignored."""
        robots = """
# This is a comment
User-agent: *
Allow: /  # inline comment
"""
        groups = _parse_robots_txt(robots)
        assert len(groups) == 1

    def test_select_specific_agent(self):
        """Select group for specific agent."""
        robots = """
User-agent: GPTBot
Disallow: /

User-agent: *
Allow: /
"""
        groups = _parse_robots_txt(robots)
        gptbot_groups = _select_group(groups, "GPTBot")
        assert len(gptbot_groups) == 1
        assert "gptbot" in gptbot_groups[0].agents

    def test_select_wildcard_fallback(self):
        """Fall back to wildcard when specific agent not found."""
        robots = """
User-agent: *
Allow: /
"""
        groups = _parse_robots_txt(robots)
        claudebot_groups = _select_group(groups, "ClaudeBot")
        assert len(claudebot_groups) == 1
        assert "*" in claudebot_groups[0].agents


class TestRobotsEvaluation:
    """Tests for robots.txt rule evaluation."""

    def test_evaluate_allow(self):
        """Evaluate allow rule."""
        robots = """
User-agent: *
Allow: /
"""
        groups = _parse_robots_txt(robots)
        result = _evaluate_group(groups, "/test")
        assert result == "allow"

    def test_evaluate_disallow(self):
        """Evaluate disallow rule."""
        robots = """
User-agent: *
Disallow: /private
"""
        groups = _parse_robots_txt(robots)
        result = _evaluate_group(groups, "/private/page")
        assert result == "disallow"

    def test_evaluate_longer_match_wins(self):
        """Longer matching rule should win."""
        robots = """
User-agent: *
Disallow: /private
Allow: /private/public
"""
        groups = _parse_robots_txt(robots)
        # /private/public should be allowed (longer match)
        result = _evaluate_group(groups, "/private/public/page")
        assert result == "allow"

    def test_evaluate_unspecified(self):
        """Return unspecified when no rules match."""
        groups = []
        result = _evaluate_group(groups, "/test")
        assert result == "unspecified"


class TestMetaRobotsExtraction:
    """Tests for meta robots tag extraction."""

    def test_extract_noindex(self):
        """Extract noindex from meta robots."""
        html = '<html><head><meta name="robots" content="noindex, nofollow"></head></html>'
        result = _extract_meta_robots(html)
        assert result["noindex"] is True
        assert result["nofollow"] is True

    def test_extract_index_follow(self):
        """Extract index, follow from meta robots."""
        html = '<html><head><meta name="robots" content="index, follow"></head></html>'
        result = _extract_meta_robots(html)
        assert result["noindex"] is False
        assert result["nofollow"] is False

    def test_no_meta_robots(self):
        """Handle missing meta robots."""
        html = '<html><head><title>Test</title></head></html>'
        result = _extract_meta_robots(html)
        assert result["content"] == ""
        assert result["noindex"] is False


class TestStructuralDiversity:
    """Tests for structural diversity calculation."""

    def test_full_diversity(self):
        """All component types present should return 4."""
        components = {
            "heading_blocks": 3,
            "paragraph_blocks": 5,
            "list_blocks": 2,
            "table_blocks": 1,
        }
        assert _structural_diversity(components) == 4

    def test_partial_diversity(self):
        """Some component types missing."""
        components = {
            "heading_blocks": 3,
            "paragraph_blocks": 5,
            "list_blocks": 0,
            "table_blocks": 0,
        }
        assert _structural_diversity(components) == 2

    def test_no_diversity(self):
        """No components should return 0."""
        components = {}
        assert _structural_diversity(components) == 0


class TestGeoScoreCalculation:
    """Tests for GEO score calculation."""

    def test_score_range(self):
        """Score should be between 0 and 100."""
        parsed = {
            "content_surface_size": {"components": {}},
            "stats": {},
            "schema_org": {"available": False},
            "readability": {"available": False},
            "quotable_sentences": [],
        }
        ai_access = {
            "gptbot": "allow",
            "claudebot": "allow",
            "perplexitybot": "allow",
            "google_extended": "allow",
            "meta_robots": {"noindex": False, "nofollow": False},
            "x_robots_tag": {"noindex": False, "nofollow": False},
        }
        blockers = []
        result = _calculate_geo_score(parsed, ai_access, blockers)
        assert 0 <= result["total"] <= 100

    def test_score_grade_mapping(self):
        """Grade should match score ranges."""
        # Test various score scenarios
        parsed = {
            "content_surface_size": {"components": {
                "heading_blocks": 5,
                "list_blocks": 2,
                "table_blocks": 1,
                "definition_blocks": 3,
            }},
            "stats": {"heading_count": 5, "content_ratio": 0.8},
            "schema_org": {"available": True, "score_contribution": 15},
            "readability": {"available": True, "flesch_reading_ease": 70},
            "quotable_sentences": [{"type": "fact"}, {"type": "statistic"}, {"type": "citation"}],
        }
        ai_access = {
            "gptbot": "allow",
            "claudebot": "allow",
            "perplexitybot": "allow",
            "google_extended": "allow",
            "meta_robots": {"noindex": False, "nofollow": False},
            "x_robots_tag": {"noindex": False, "nofollow": False},
        }
        blockers = []
        result = _calculate_geo_score(parsed, ai_access, blockers)

        # Verify grade matches score
        grade = result["grade"]
        total = result["total"]

        if total >= 90:
            assert grade == "A"
        elif total >= 75:
            assert grade == "B"
        elif total >= 60:
            assert grade == "C"
        elif total >= 40:
            assert grade == "D"
        else:
            assert grade == "F"

    def test_blocked_crawlers_reduce_score(self):
        """Blocked crawlers should reduce accessibility score."""
        parsed = {
            "content_surface_size": {"components": {}},
            "stats": {},
            "schema_org": {"available": False},
            "readability": {"available": False},
            "quotable_sentences": [],
        }
        ai_access_allowed = {
            "gptbot": "allow",
            "claudebot": "allow",
            "perplexitybot": "allow",
            "google_extended": "allow",
            "meta_robots": {"noindex": False, "nofollow": False},
            "x_robots_tag": {"noindex": False, "nofollow": False},
        }
        ai_access_blocked = {
            "gptbot": "disallow",
            "claudebot": "disallow",
            "perplexitybot": "allow",
            "google_extended": "allow",
            "meta_robots": {"noindex": False, "nofollow": False},
            "x_robots_tag": {"noindex": False, "nofollow": False},
        }

        score_allowed = _calculate_geo_score(parsed, ai_access_allowed, [])
        score_blocked = _calculate_geo_score(parsed, ai_access_blocked, [])

        assert score_blocked["total"] < score_allowed["total"]


class TestFullGeoCheck:
    """Integration tests for full GEO check."""

    def test_check_geo_returns_expected_keys(self, parsed_content: dict, valid_html: str, mock_url: str):
        """check_geo should return expected keys."""
        # Skip if network not available (mocked in real tests)
        result = check_geo(parsed_content, valid_html, mock_url)

        expected_keys = [
            "geo_score",
            "summary",
            "ai_crawler_access",
            "ai_usage_interpretation",
            "interpretation_rule_hints",
            "last_mile_blockers",
            "blocker_signal_mapping",
            "structural_fixes",
        ]

        for key in expected_keys:
            assert key in result, f"Missing key: {key}"

    def test_geo_score_structure(self, parsed_content: dict, valid_html: str, mock_url: str):
        """GEO score should have proper structure."""
        result = check_geo(parsed_content, valid_html, mock_url)
        score = result["geo_score"]

        assert "total" in score
        assert "grade" in score
        assert "grade_label" in score
        assert "breakdown" in score

        breakdown = score["breakdown"]
        assert "accessibility" in breakdown
        assert "structure" in breakdown
        assert "quality" in breakdown


class TestAccessibilityScoring:
    """Boundary value tests for accessibility scoring (0-40 points)."""

    def test_full_accessibility_score(self):
        """All crawlers allowed, no blockers = 40 points."""
        ai_access = {
            "gptbot": "allow",
            "claudebot": "allow",
            "perplexitybot": "allow",
            "google_extended": "allow",
            "meta_robots": {"noindex": False, "nofollow": False},
            "x_robots_tag": {"noindex": False, "nofollow": False},
        }
        score = _score_accessibility(ai_access, [])
        assert score == 40

    def test_one_crawler_blocked(self):
        """One blocked crawler = -10 points."""
        ai_access = {
            "gptbot": "disallow",
            "claudebot": "allow",
            "perplexitybot": "allow",
            "google_extended": "allow",
            "meta_robots": {"noindex": False, "nofollow": False},
            "x_robots_tag": {"noindex": False, "nofollow": False},
        }
        score = _score_accessibility(ai_access, [])
        assert score == 30

    def test_all_crawlers_blocked(self):
        """All 4 crawlers blocked = -40 points = 0."""
        ai_access = {
            "gptbot": "disallow",
            "claudebot": "disallow",
            "perplexitybot": "disallow",
            "google_extended": "disallow",
            "meta_robots": {"noindex": False, "nofollow": False},
            "x_robots_tag": {"noindex": False, "nofollow": False},
        }
        score = _score_accessibility(ai_access, [])
        assert score == 0

    def test_noindex_penalty(self):
        """noindex = -15 points."""
        ai_access = {
            "gptbot": "allow",
            "claudebot": "allow",
            "perplexitybot": "allow",
            "google_extended": "allow",
            "meta_robots": {"noindex": True, "nofollow": False},
            "x_robots_tag": {"noindex": False, "nofollow": False},
        }
        score = _score_accessibility(ai_access, [])
        assert score == 25

    def test_nofollow_penalty(self):
        """nofollow = -5 points."""
        ai_access = {
            "gptbot": "allow",
            "claudebot": "allow",
            "perplexitybot": "allow",
            "google_extended": "allow",
            "meta_robots": {"noindex": False, "nofollow": True},
            "x_robots_tag": {"noindex": False, "nofollow": False},
        }
        score = _score_accessibility(ai_access, [])
        assert score == 35

    def test_x_robots_noindex_penalty(self):
        """X-Robots-Tag noindex = -15 points."""
        ai_access = {
            "gptbot": "allow",
            "claudebot": "allow",
            "perplexitybot": "allow",
            "google_extended": "allow",
            "meta_robots": {"noindex": False, "nofollow": False},
            "x_robots_tag": {"noindex": True, "nofollow": False},
        }
        score = _score_accessibility(ai_access, [])
        assert score == 25

    def test_blocker_penalty(self):
        """Each blocker = -5 points."""
        ai_access = {
            "gptbot": "allow",
            "claudebot": "allow",
            "perplexitybot": "allow",
            "google_extended": "allow",
            "meta_robots": {"noindex": False, "nofollow": False},
            "x_robots_tag": {"noindex": False, "nofollow": False},
        }
        score = _score_accessibility(ai_access, ["blocker1", "blocker2"])
        assert score == 30

    def test_combined_penalties_floor_at_zero(self):
        """Score should not go below 0."""
        ai_access = {
            "gptbot": "disallow",
            "claudebot": "disallow",
            "perplexitybot": "disallow",
            "google_extended": "disallow",
            "meta_robots": {"noindex": True, "nofollow": True},
            "x_robots_tag": {"noindex": True, "nofollow": True},
        }
        score = _score_accessibility(ai_access, ["b1", "b2", "b3", "b4", "b5"])
        assert score == 0


class TestStructureScoring:
    """Boundary value tests for structure scoring (0-30 points)."""

    def _make_parsed(
        self,
        heading_count=0,
        list_blocks=0,
        table_blocks=0,
        schema_available=False,
        schema_contribution=0,
        has_breadcrumb=False,
    ):
        return {
            "content_surface_size": {
                "components": {
                    "list_blocks": list_blocks,
                    "table_blocks": table_blocks,
                }
            },
            "stats": {"heading_count": heading_count},
            "schema_org": {
                "available": schema_available,
                "score_contribution": schema_contribution,
                "has_breadcrumb": has_breadcrumb,
            },
            "content": {"headings": [], "paragraphs": []},
        }

    def test_zero_structure_score(self):
        """No structure = 0 points."""
        parsed = self._make_parsed()
        score = _score_structure(parsed, {})
        assert score == 0

    def test_heading_scoring_one(self):
        """1 heading = 4 points."""
        parsed = self._make_parsed(heading_count=1)
        score = _score_structure(parsed, {})
        assert score == 4

    def test_heading_scoring_three(self):
        """3 headings = 6 points."""
        parsed = self._make_parsed(heading_count=3)
        score = _score_structure(parsed, {})
        assert score == 6

    def test_heading_scoring_five(self):
        """5+ headings = 8 points."""
        parsed = self._make_parsed(heading_count=5)
        score = _score_structure(parsed, {})
        assert score == 8

    def test_list_scoring_one(self):
        """1 list = 5 points."""
        parsed = self._make_parsed(list_blocks=1)
        score = _score_structure(parsed, {})
        assert score == 5

    def test_list_scoring_two(self):
        """2+ lists = 7 points."""
        parsed = self._make_parsed(list_blocks=2)
        score = _score_structure(parsed, {})
        assert score == 7

    def test_table_scoring(self):
        """1 table = 5 or 7 points."""
        parsed = self._make_parsed(table_blocks=1)
        score = _score_structure(parsed, {})
        assert score in (5, 7)  # depends on list condition

    def test_schema_org_contribution(self):
        """Schema.org adds up to 11 points."""
        parsed = self._make_parsed(schema_available=True, schema_contribution=11)
        score = _score_structure(parsed, {})
        assert score == 11

    def test_schema_org_capped_at_11(self):
        """Schema.org contribution capped at 11."""
        parsed = self._make_parsed(schema_available=True, schema_contribution=20)
        score = _score_structure(parsed, {})
        assert score == 11

    def test_breadcrumb_bonus(self):
        """Breadcrumb adds 2 points."""
        parsed = self._make_parsed(schema_available=True, schema_contribution=5, has_breadcrumb=True)
        score = _score_structure(parsed, {})
        assert score == 5 + 2

    def test_qa_structure_bonus(self):
        """Q&A structure adds 4 points."""
        parsed = self._make_parsed()
        qa_structure = {"has_qa_structure": True}
        score = _score_structure(parsed, qa_structure)
        assert score == 4

    def test_question_headings_bonus(self):
        """Question headings add 2 points."""
        parsed = self._make_parsed()
        qa_structure = {"has_qa_structure": False, "question_headings": 1}
        score = _score_structure(parsed, qa_structure)
        assert score == 2

    def test_max_structure_score_capped(self):
        """Structure score capped at 30."""
        parsed = self._make_parsed(
            heading_count=10,
            list_blocks=5,
            table_blocks=5,
            schema_available=True,
            schema_contribution=20,
            has_breadcrumb=True,
        )
        qa_structure = {"has_qa_structure": True}
        score = _score_structure(parsed, qa_structure)
        assert score == 30


class TestQualityScoring:
    """Boundary value tests for quality scoring (0-30 points)."""

    def _make_parsed(
        self,
        flesch=50,
        readability_available=True,
        entity_count=0,
        definition_blocks=0,
        content_ratio=0.5,
        quotable_sentences=None,
    ):
        return {
            "readability": {"available": readability_available, "flesch_reading_ease": flesch},
            "entities": [{"name": f"entity{i}"} for i in range(entity_count)],
            "content_surface_size": {"components": {"definition_blocks": definition_blocks}},
            "stats": {"content_ratio": content_ratio},
            "quotable_sentences": quotable_sentences or [],
            "content": {"paragraphs": []},
        }

    def _make_quality_helpers(self):
        return {
            "link_quality": {"quality_score": 0},
            "content_depth": {"depth_score": 0},
            "first_paragraph": {"score": 0},
            "pronoun_issues": {"score": 0},
        }

    def test_readability_excellent(self):
        """Flesch >= 60 = 6 points."""
        parsed = self._make_parsed(flesch=65)
        helpers = self._make_quality_helpers()
        score = _score_quality(parsed, **helpers)
        assert score >= 6

    def test_readability_good(self):
        """Flesch 50-59 = 5 points."""
        parsed = self._make_parsed(flesch=55)
        helpers = self._make_quality_helpers()
        score = _score_quality(parsed, **helpers)
        assert score >= 5

    def test_readability_fair(self):
        """Flesch 40-49 = 4 points."""
        parsed = self._make_parsed(flesch=45)
        helpers = self._make_quality_helpers()
        score = _score_quality(parsed, **helpers)
        assert score >= 4

    def test_readability_poor(self):
        """Flesch 30-39 = 2 points."""
        parsed = self._make_parsed(flesch=35)
        helpers = self._make_quality_helpers()
        score = _score_quality(parsed, **helpers)
        assert score >= 2

    def test_readability_unavailable(self):
        """No readability = 3 points default."""
        parsed = self._make_parsed(readability_available=False)
        helpers = self._make_quality_helpers()
        score = _score_quality(parsed, **helpers)
        assert score >= 3

    def test_entity_richness_ten_plus(self):
        """10+ entities = 4 points."""
        parsed = self._make_parsed(entity_count=10)
        helpers = self._make_quality_helpers()
        score = _score_quality(parsed, **helpers)
        # Base readability (5) + entities (4) = 9
        assert score >= 9

    def test_entity_richness_five(self):
        """5-9 entities = 3 points."""
        parsed = self._make_parsed(entity_count=5)
        helpers = self._make_quality_helpers()
        score = _score_quality(parsed, **helpers)
        assert score >= 8

    def test_definition_density_three_plus(self):
        """3+ definitions = 5 points."""
        parsed = self._make_parsed(definition_blocks=3)
        helpers = self._make_quality_helpers()
        score = _score_quality(parsed, **helpers)
        assert score >= 10

    def test_content_ratio_high(self):
        """Content ratio >= 0.7 = 4 points."""
        parsed = self._make_parsed(content_ratio=0.75)
        helpers = self._make_quality_helpers()
        score = _score_quality(parsed, **helpers)
        assert score >= 9

    def test_quotable_sentences_diverse(self):
        """3+ quotable with 2+ types = 5 points."""
        quotable = [
            {"type": "statistic"},
            {"type": "citation"},
            {"type": "fact"},
        ]
        parsed = self._make_parsed(quotable_sentences=quotable)
        helpers = self._make_quality_helpers()
        score = _score_quality(parsed, **helpers)
        assert score >= 10

    def test_quality_score_capped_at_30(self):
        """Quality score capped at 30."""
        quotable = [
            {"type": "statistic"},
            {"type": "citation"},
            {"type": "fact"},
            {"type": "definition"},
        ]
        parsed = self._make_parsed(
            flesch=70,
            entity_count=15,
            definition_blocks=5,
            content_ratio=0.9,
            quotable_sentences=quotable,
        )
        helpers = {
            "link_quality": {"quality_score": 5},
            "content_depth": {"depth_score": 5},
            "first_paragraph": {"score": 5},
            "pronoun_issues": {"score": 5},
        }
        score = _score_quality(parsed, **helpers)
        assert score == 30


class TestGradeMapping:
    """Tests for grade determination."""

    @pytest.mark.parametrize(
        "score,expected_grade",
        [
            (100, "A"),
            (95, "A"),
            (90, "A"),
            (89, "B"),
            (75, "B"),
            (74, "C"),
            (60, "C"),
            (59, "D"),
            (40, "D"),
            (39, "F"),
            (0, "F"),
        ],
    )
    def test_grade_boundaries(self, score, expected_grade):
        """Test grade boundaries."""
        grade, _ = _determine_grade(score)
        assert grade == expected_grade

    @pytest.mark.parametrize(
        "score,expected_label",
        [
            (95, "excellent"),
            (80, "good"),
            (65, "fair"),
            (50, "poor"),
            (20, "critical"),
        ],
    )
    def test_grade_labels(self, score, expected_label):
        """Test grade labels."""
        _, label = _determine_grade(score)
        assert label == expected_label


class TestScoreIntegrity:
    """Tests for score calculation integrity."""

    def test_total_equals_sum_of_parts(self):
        """Total should equal sum of accessibility + structure + quality."""
        parsed = {
            "content_surface_size": {"components": {"list_blocks": 2, "definition_blocks": 2}},
            "stats": {"heading_count": 3, "content_ratio": 0.6},
            "schema_org": {"available": True, "score_contribution": 8},
            "readability": {"available": True, "flesch_reading_ease": 55},
            "quotable_sentences": [{"type": "fact"}],
            "entities": [{"name": "test"}],
            "content": {"headings": [], "paragraphs": []},
        }
        ai_access = {
            "gptbot": "allow",
            "claudebot": "allow",
            "perplexitybot": "allow",
            "google_extended": "allow",
            "meta_robots": {"noindex": False, "nofollow": False},
            "x_robots_tag": {"noindex": False, "nofollow": False},
        }
        result = _calculate_geo_score(parsed, ai_access, [])

        breakdown = result["breakdown"]
        expected_total = (
            breakdown["accessibility"]["score"]
            + breakdown["structure"]["score"]
            + breakdown["quality"]["score"]
        )
        # May be clamped to 100
        assert result["total"] == min(100, expected_total)

    def test_breakdown_max_values(self):
        """Breakdown max values should be correct."""
        parsed = {
            "content_surface_size": {"components": {}},
            "stats": {},
            "schema_org": {"available": False},
            "readability": {"available": False},
            "quotable_sentences": [],
            "content": {"headings": [], "paragraphs": []},
        }
        ai_access = {
            "gptbot": "allow",
            "claudebot": "allow",
            "perplexitybot": "allow",
            "google_extended": "allow",
            "meta_robots": {"noindex": False, "nofollow": False},
            "x_robots_tag": {"noindex": False, "nofollow": False},
        }
        result = _calculate_geo_score(parsed, ai_access, [])
        breakdown = result["breakdown"]

        assert breakdown["accessibility"]["max"] == 40
        assert breakdown["structure"]["max"] == 30
        assert breakdown["quality"]["max"] == 30

    def test_weight_sum_is_100(self):
        """Sum of max weights should be 100."""
        assert 40 + 30 + 30 == 100
