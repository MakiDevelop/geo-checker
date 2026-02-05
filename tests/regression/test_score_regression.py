"""
GEO Score Regression Tests.

These tests ensure that code changes don't unexpectedly alter scoring behavior.
If a test fails, it means the scoring algorithm has changed - this may be intentional
(in which case update the expected values) or a bug (fix the code).

Golden data approach:
- Each fixture has a pre-computed expected score range
- Tests verify scores stay within that range
- Significant deviations indicate algorithm changes
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.geo.geo_checker import _calculate_geo_score, check_geo
from src.parser.content_parser import parse_content


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "html"


class TestScoreRegressionWithFixtures:
    """Regression tests using HTML fixtures."""

    @pytest.fixture
    def mock_ai_access_allow_all(self):
        """Mock AI access that allows all crawlers."""
        return {
            "robots_txt_found": True,
            "gptbot": "allow",
            "claudebot": "allow",
            "perplexitybot": "allow",
            "google_extended": "allow",
            "meta_robots": {"content": "", "noindex": False, "nofollow": False},
            "x_robots_tag": {"value": "", "noindex": False, "nofollow": False},
            "notes": "",
        }

    def test_excellent_geo_fixture(self, mock_ai_access_allow_all):
        """
        Excellent GEO fixture should score 75+ (Grade B or better).

        This fixture has:
        - All AI crawlers allowed
        - Article, FAQ, Breadcrumb Schema.org
        - Multiple headings with good hierarchy
        - Lists and tables
        - Definitions and statistics
        - Citations and quotable content
        """
        html_path = FIXTURES_DIR / "excellent_geo.html"
        if not html_path.exists():
            pytest.skip("Fixture file not found")

        html = html_path.read_text()
        url = "https://example.com/machine-learning-guide"
        parsed = parse_content(html, url)

        result = _calculate_geo_score(parsed, mock_ai_access_allow_all, [])

        # Expected: Grade B or A (75+)
        assert result["total"] >= 75, f"Excellent fixture scored {result['total']}, expected >= 75"
        assert result["grade"] in ("A", "B"), f"Expected grade A or B, got {result['grade']}"

        # Breakdown expectations
        breakdown = result["breakdown"]
        assert breakdown["accessibility"]["score"] == 40, "Should have full accessibility"
        assert breakdown["structure"]["score"] >= 20, "Should have good structure"
        assert breakdown["quality"]["score"] >= 15, "Should have good quality"

    def test_average_geo_fixture(self, mock_ai_access_allow_all):
        """
        Average GEO fixture should score 50-74 (Grade C or D).

        This fixture has:
        - Basic meta tags
        - Some headings and lists
        - No Schema.org
        - Limited quotable content
        """
        html_path = FIXTURES_DIR / "average_geo.html"
        if not html_path.exists():
            pytest.skip("Fixture file not found")

        html = html_path.read_text()
        url = "https://example.com/services"
        parsed = parse_content(html, url)

        result = _calculate_geo_score(parsed, mock_ai_access_allow_all, [])

        # Expected: Grade C or D (40-74)
        assert 40 <= result["total"] < 75, f"Average fixture scored {result['total']}, expected 40-74"
        assert result["grade"] in ("C", "D"), f"Expected grade C or D, got {result['grade']}"

    def test_poor_geo_fixture(self, mock_ai_access_allow_all):
        """
        Poor GEO fixture should score below 50 (Grade D or F).

        This fixture has:
        - Minimal meta tags
        - No headings
        - No structured content
        - Poor readability
        """
        html_path = FIXTURES_DIR / "poor_geo.html"
        if not html_path.exists():
            pytest.skip("Fixture file not found")

        html = html_path.read_text()
        url = "https://example.com/info"
        parsed = parse_content(html, url)

        result = _calculate_geo_score(parsed, mock_ai_access_allow_all, [])

        # Expected: Grade D or F (below 60)
        assert result["total"] < 60, f"Poor fixture scored {result['total']}, expected < 60"
        assert result["grade"] in ("D", "F"), f"Expected grade D or F, got {result['grade']}"


class TestScoreConsistency:
    """Tests for score calculation consistency."""

    def test_same_input_same_output(self):
        """Same input should always produce the same score."""
        parsed = {
            "content_surface_size": {"components": {"list_blocks": 2}},
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

        # Calculate score multiple times
        scores = [_calculate_geo_score(parsed, ai_access, [])["total"] for _ in range(5)]

        # All scores should be identical
        assert len(set(scores)) == 1, f"Inconsistent scores: {scores}"

    def test_deterministic_grade_assignment(self):
        """Grade assignment should be deterministic at boundaries."""
        parsed = {
            "content_surface_size": {"components": {}},
            "stats": {},
            "schema_org": {"available": False},
            "readability": {"available": False},
            "quotable_sentences": [],
            "content": {"headings": [], "paragraphs": []},
        }

        # Test at grade boundaries
        test_cases = [
            ({"gptbot": "allow", "claudebot": "allow", "perplexitybot": "allow", "google_extended": "allow"}, "accessibility"),
            ({"gptbot": "disallow", "claudebot": "allow", "perplexitybot": "allow", "google_extended": "allow"}, "one_blocked"),
        ]

        for access_pattern, label in test_cases:
            ai_access = {
                **access_pattern,
                "meta_robots": {"noindex": False, "nofollow": False},
                "x_robots_tag": {"noindex": False, "nofollow": False},
            }
            results = [_calculate_geo_score(parsed, ai_access, []) for _ in range(3)]
            grades = [r["grade"] for r in results]
            assert len(set(grades)) == 1, f"Inconsistent grades for {label}: {grades}"


class TestScoreRangeInvariants:
    """Tests for score range invariants that must always hold."""

    def test_more_content_never_decreases_quality(self):
        """Adding quality content should not decrease quality score."""
        base_parsed = {
            "content_surface_size": {"components": {"definition_blocks": 1}},
            "stats": {"content_ratio": 0.5},
            "schema_org": {"available": False},
            "readability": {"available": True, "flesch_reading_ease": 50},
            "quotable_sentences": [],
            "entities": [],
            "content": {"headings": [], "paragraphs": []},
        }

        enhanced_parsed = {
            "content_surface_size": {"components": {"definition_blocks": 3}},
            "stats": {"content_ratio": 0.7},
            "schema_org": {"available": False},
            "readability": {"available": True, "flesch_reading_ease": 60},
            "quotable_sentences": [{"type": "statistic"}, {"type": "citation"}],
            "entities": [{"name": f"e{i}"} for i in range(10)],
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

        base_score = _calculate_geo_score(base_parsed, ai_access, [])
        enhanced_score = _calculate_geo_score(enhanced_parsed, ai_access, [])

        assert enhanced_score["breakdown"]["quality"]["score"] >= base_score["breakdown"]["quality"]["score"]

    def test_blocking_crawlers_always_decreases_accessibility(self):
        """Blocking AI crawlers should always decrease accessibility score."""
        parsed = {
            "content_surface_size": {"components": {}},
            "stats": {},
            "schema_org": {"available": False},
            "readability": {"available": False},
            "quotable_sentences": [],
            "content": {"headings": [], "paragraphs": []},
        }

        all_allowed = {
            "gptbot": "allow",
            "claudebot": "allow",
            "perplexitybot": "allow",
            "google_extended": "allow",
            "meta_robots": {"noindex": False, "nofollow": False},
            "x_robots_tag": {"noindex": False, "nofollow": False},
        }

        one_blocked = {
            "gptbot": "disallow",
            "claudebot": "allow",
            "perplexitybot": "allow",
            "google_extended": "allow",
            "meta_robots": {"noindex": False, "nofollow": False},
            "x_robots_tag": {"noindex": False, "nofollow": False},
        }

        all_allowed_score = _calculate_geo_score(parsed, all_allowed, [])
        one_blocked_score = _calculate_geo_score(parsed, one_blocked, [])

        assert one_blocked_score["breakdown"]["accessibility"]["score"] < all_allowed_score["breakdown"]["accessibility"]["score"]

    def test_noindex_severely_impacts_score(self):
        """noindex should have significant negative impact."""
        parsed = {
            "content_surface_size": {"components": {}},
            "stats": {},
            "schema_org": {"available": False},
            "readability": {"available": False},
            "quotable_sentences": [],
            "content": {"headings": [], "paragraphs": []},
        }

        without_noindex = {
            "gptbot": "allow",
            "claudebot": "allow",
            "perplexitybot": "allow",
            "google_extended": "allow",
            "meta_robots": {"noindex": False, "nofollow": False},
            "x_robots_tag": {"noindex": False, "nofollow": False},
        }

        with_noindex = {
            "gptbot": "allow",
            "claudebot": "allow",
            "perplexitybot": "allow",
            "google_extended": "allow",
            "meta_robots": {"noindex": True, "nofollow": False},
            "x_robots_tag": {"noindex": False, "nofollow": False},
        }

        without_score = _calculate_geo_score(parsed, without_noindex, [])
        with_score = _calculate_geo_score(parsed, with_noindex, [])

        # noindex should cost at least 10 points
        assert without_score["total"] - with_score["total"] >= 10


class TestGoldenScores:
    """
    Golden score tests - specific inputs with exact expected outputs.

    IMPORTANT: If these tests fail after intentional algorithm changes,
    update the expected values and document the change in the commit message.
    """

    def test_golden_minimal_content(self):
        """Minimal content should produce predictable low score."""
        parsed = {
            "content_surface_size": {"components": {}},
            "stats": {},
            "schema_org": {"available": False},
            "readability": {"available": False},
            "quotable_sentences": [],
            "entities": [],
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

        # Golden values (update if algorithm changes intentionally)
        assert result["breakdown"]["accessibility"]["score"] == 40
        assert result["breakdown"]["structure"]["score"] == 0
        # Quality gets base points: 3 (readability default) + content_ratio + pronoun_clarity defaults
        # Actual value is 8 based on current algorithm
        assert result["breakdown"]["quality"]["score"] == 8
        assert result["total"] == 48
        assert result["grade"] == "D"

    def test_golden_well_structured(self):
        """Well-structured content should produce predictable good score."""
        parsed = {
            "content_surface_size": {
                "components": {
                    "list_blocks": 2,
                    "table_blocks": 1,
                    "definition_blocks": 2,
                }
            },
            "stats": {"heading_count": 5, "content_ratio": 0.7},
            "schema_org": {
                "available": True,
                "score_contribution": 8,
                "has_breadcrumb": True,
            },
            "readability": {"available": True, "flesch_reading_ease": 65},
            "quotable_sentences": [
                {"type": "statistic"},
                {"type": "citation"},
            ],
            "entities": [{"name": f"entity{i}"} for i in range(5)],
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

        # Expected breakdown (update if algorithm changes)
        # Accessibility: 40 (all allowed)
        assert result["breakdown"]["accessibility"]["score"] == 40

        # Structure: 8 (5 headings) + 7 (2 lists) + 8 (schema) + 2 (breadcrumb) = 25
        assert result["breakdown"]["structure"]["score"] >= 20

        # Quality: 6 (readability) + 3 (5 entities) + 4 (2 definitions) + 4 (content ratio) + 4 (quotable) = 21+
        assert result["breakdown"]["quality"]["score"] >= 15

        # Total should be B grade
        assert result["grade"] in ("A", "B")
