"""Regression tests for _convert_geo_result (serializer completeness).

Scope: the raw check_geo() output dict has grown over Phase 3/4 (freshness,
eeat, image_quality, llms_txt, citation_simulation) and the AICrawlerAccess
now carries a `crawlers` dict with per-bot metadata. These tests guard that
the serializer actually propagates all of those fields to the Pydantic
response model instead of silently dropping them.
"""
from __future__ import annotations

from app.api.models.responses import (
    CitationSimulation,
    CrawlerStatus,
    EEATAssessment,
    FreshnessAssessment,
    GeoAnalysisResult,
    ImageQualityAssessment,
    LlmsTxtAssessment,
)
from app.api.v1.endpoints.jobs import _convert_geo_result


def _minimal_geo_fixture() -> dict:
    """Return a check_geo()-shaped dict covering every expected field."""
    return {
        "geo_score": {
            "total": 78,
            "grade": "B",
            "grade_label": "good",
            "breakdown": {
                "accessibility": {"score": 35, "max": 40, "percentage": 88},
                "structure": {"score": 22, "max": 30, "percentage": 73},
                "quality": {"score": 21, "max": 30, "percentage": 70},
            },
        },
        "summary": {
            "summary_key": "summary.ok",
            "issues": {
                "critical": [{"key": "noindex_set"}],
                "warning": [{"key": "thin_content"}],
                "good": [{"key": "has_headings"}],
            },
            "priority_fixes": [
                {
                    "priority": "critical",
                    "action": "Remove noindex",
                    "impact": "high",
                },
            ],
        },
        "ai_crawler_access": {
            "robots_txt_found": True,
            "crawlers": {
                "gptbot": {
                    "status": "allow",
                    "display": "GPTBot",
                    "vendor": "OpenAI",
                    "purpose": "training",
                },
                "claudebot": {
                    "status": "disallow",
                    "display": "ClaudeBot",
                    "vendor": "Anthropic",
                    "purpose": "training",
                },
            },
            "meta_robots": {
                "content": "index,follow",
                "noindex": False,
                "nofollow": False,
            },
            "x_robots_tag": {"value": "", "noindex": False, "nofollow": False},
            "notes": "",
            "gptbot": "allow",
            "claudebot": "disallow",
            "perplexitybot": "unspecified",
            "google_extended": "unspecified",
        },
        "ai_usage_interpretation": {"type": "article"},
        "last_mile_blockers": ["thin_content"],
        "structural_fixes": [{"key": "add_faq_section"}],
        "extended_metrics": {
            "qa_structure": {
                "has_qa_structure": True,
                "question_headings": 3,
                "question_paragraphs": 5,
            },
            "link_quality": {
                "total_links": 10,
                "internal_links": 6,
                "external_links": 4,
                "descriptive_anchors": 7,
                "quality_score": 2,
            },
            "content_depth": {
                "word_count": 1500,
                "unique_heading_levels": 3,
                "has_deep_hierarchy": True,
                "depth_score": 5,
            },
            "entity_count": 12,
            "first_paragraph": {
                "has_strong_opening": True,
                "first_paragraph_length": 180,
                "score": 3,
            },
            "pronoun_clarity": {
                "paragraphs_starting_with_pronoun": 1,
                "total_pronouns_in_first_10": 4,
                "score": 2,
            },
            "citation_potential": {
                "score": 8,
                "max_score": 11,
                "level": "high",
                "signals": ["qa_structure", "citation_density"],
            },
            "freshness": {
                "date_published": "2026-01-01",
                "date_modified": "2026-03-15",
                "has_dates": True,
                "score": 3,
                "max_score": 4,
            },
            "eeat": {
                "author_name": "Maki Chiang",
                "score": 5,
                "max_score": 6,
                "signals": ["author_identified", "date_present"],
            },
            "image_quality": {
                "total_images": 4,
                "alt_coverage": 0.75,
                "descriptive_ratio": 0.5,
                "score": 2,
                "max_score": 3,
            },
            "llms_txt": {
                "found": True,
                "path": "/llms.txt",
                "score": 2,
                "max_score": 2,
            },
            "citation_simulation": {
                "mode": "rule_based",
                "mock_query": "What is GEO?",
                "cited_snippets": [{"text": "GEO means ..."}],
                "citation_preview": "GEO means ...",
                "coverage": {
                    "score": 5,
                    "max_score": 7,
                    "readiness": "moderate",
                    "signals": ["has_definition", "has_faq"],
                },
            },
        },
    }


class TestConvertGeoResultCrawlers:
    def test_crawlers_dict_populated(self):
        result = _convert_geo_result(_minimal_geo_fixture())
        assert isinstance(result, GeoAnalysisResult)
        crawlers = result.ai_crawler_access.crawlers
        assert "gptbot" in crawlers
        assert "claudebot" in crawlers
        assert isinstance(crawlers["gptbot"], CrawlerStatus)
        assert crawlers["gptbot"].status == "allow"
        assert crawlers["gptbot"].display == "GPTBot"
        assert crawlers["gptbot"].vendor == "OpenAI"
        assert crawlers["claudebot"].status == "disallow"

    def test_crawlers_empty_when_missing(self):
        fixture = _minimal_geo_fixture()
        fixture["ai_crawler_access"].pop("crawlers", None)
        result = _convert_geo_result(fixture)
        assert result.ai_crawler_access.crawlers == {}

    def test_legacy_flat_keys_still_serialized(self):
        result = _convert_geo_result(_minimal_geo_fixture())
        assert result.ai_crawler_access.gptbot == "allow"
        assert result.ai_crawler_access.claudebot == "disallow"


class TestConvertGeoResultPhase3Metrics:
    def test_freshness_populated(self):
        result = _convert_geo_result(_minimal_geo_fixture())
        fresh = result.extended_metrics.freshness
        assert isinstance(fresh, FreshnessAssessment)
        assert fresh.date_published == "2026-01-01"
        assert fresh.date_modified == "2026-03-15"
        assert fresh.has_dates is True
        assert fresh.score == 3

    def test_eeat_populated(self):
        result = _convert_geo_result(_minimal_geo_fixture())
        eeat = result.extended_metrics.eeat
        assert isinstance(eeat, EEATAssessment)
        assert eeat.author_name == "Maki Chiang"
        assert eeat.score == 5
        assert "author_identified" in eeat.signals

    def test_image_quality_populated(self):
        result = _convert_geo_result(_minimal_geo_fixture())
        iq = result.extended_metrics.image_quality
        assert isinstance(iq, ImageQualityAssessment)
        assert iq.total_images == 4
        assert iq.alt_coverage == 0.75
        assert iq.descriptive_ratio == 0.5
        assert iq.score == 2

    def test_llms_txt_populated(self):
        result = _convert_geo_result(_minimal_geo_fixture())
        llms = result.extended_metrics.llms_txt
        assert isinstance(llms, LlmsTxtAssessment)
        assert llms.found is True
        assert llms.path == "/llms.txt"
        assert llms.score == 2

    def test_optional_metrics_none_when_missing(self):
        fixture = _minimal_geo_fixture()
        for key in (
            "freshness",
            "eeat",
            "image_quality",
            "llms_txt",
            "citation_simulation",
        ):
            fixture["extended_metrics"].pop(key, None)
        result = _convert_geo_result(fixture)
        assert result.extended_metrics.freshness is None
        assert result.extended_metrics.eeat is None
        assert result.extended_metrics.image_quality is None
        assert result.extended_metrics.llms_txt is None
        assert result.extended_metrics.citation_simulation is None


class TestConvertGeoResultPhase4CitationSimulation:
    def test_model_dump_preserves_serializer_shape(self):
        fixture = _minimal_geo_fixture()
        dumped = _convert_geo_result(fixture).model_dump()
        assert dumped.keys() == fixture.keys()
        assert (
            dumped["ai_crawler_access"]["crawlers"].keys()
            == fixture["ai_crawler_access"]["crawlers"].keys()
        )
        assert {"freshness", "eeat", "image_quality", "llms_txt", "citation_simulation"} <= dumped[
            "extended_metrics"
        ].keys()
        assert (
            dumped["extended_metrics"]["citation_simulation"]["coverage"].keys()
            == fixture["extended_metrics"]["citation_simulation"]["coverage"].keys()
        )

    def test_citation_simulation_populated(self):
        result = _convert_geo_result(_minimal_geo_fixture())
        cs = result.extended_metrics.citation_simulation
        assert isinstance(cs, CitationSimulation)
        assert cs.mode == "rule_based"
        assert cs.mock_query == "What is GEO?"
        assert cs.citation_preview.startswith("GEO means")
        assert cs.cited_snippets
        assert cs.cited_snippets[0]["text"].startswith("GEO means")

    def test_citation_simulation_coverage_populated(self):
        result = _convert_geo_result(_minimal_geo_fixture())
        cs = result.extended_metrics.citation_simulation
        assert cs is not None
        assert cs.coverage is not None
        assert cs.coverage.score == 5
        assert cs.coverage.max_score == 7
        assert cs.coverage.readiness == "moderate"
        assert "has_definition" in cs.coverage.signals

    def test_citation_simulation_coverage_optional(self):
        fixture = _minimal_geo_fixture()
        fixture["extended_metrics"]["citation_simulation"].pop("coverage", None)
        result = _convert_geo_result(fixture)
        cs = result.extended_metrics.citation_simulation
        assert cs is not None
        assert cs.coverage is None
