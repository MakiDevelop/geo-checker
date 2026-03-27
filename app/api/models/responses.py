"""API response models."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# === Score Breakdown Models ===


class ScoreBreakdownItem(BaseModel):
    """Individual score breakdown component."""

    score: int = Field(..., ge=0, description="Achieved score")
    max: int = Field(..., gt=0, description="Maximum possible score")
    percentage: int = Field(..., ge=0, le=100, description="Score percentage")


class GeoScoreBreakdown(BaseModel):
    """Detailed breakdown of GEO score by dimension."""

    accessibility: ScoreBreakdownItem
    structure: ScoreBreakdownItem
    quality: ScoreBreakdownItem


class GeoScore(BaseModel):
    """GEO Score summary."""

    total: int = Field(..., ge=0, le=100, description="Total GEO score (0-100)")
    grade: Literal["A", "B", "C", "D", "F"] = Field(..., description="Letter grade")
    grade_label: str = Field(..., description="Human-readable grade label")
    breakdown: GeoScoreBreakdown


# === Issue Models ===


class Issue(BaseModel):
    """Individual issue or recommendation."""

    key: str = Field(..., description="Issue identifier key")
    crawlers: list[str] | None = Field(
        default=None, description="Affected crawlers (if applicable)"
    )


class IssuesSummary(BaseModel):
    """Categorized issues summary."""

    critical: list[Issue] = Field(default_factory=list)
    warning: list[Issue] = Field(default_factory=list)
    good: list[Issue] = Field(default_factory=list)


class PriorityFix(BaseModel):
    """Recommended fix with priority."""

    priority: Literal["critical", "recommended", "suggested"]
    action: str = Field(..., description="Action to take")
    impact: Literal["high", "medium", "low"]


class Summary(BaseModel):
    """Analysis summary with issues and recommendations."""

    summary_key: str
    issues: IssuesSummary
    priority_fixes: list[PriorityFix]


# === AI Crawler Access Models ===


class MetaRobots(BaseModel):
    """Meta robots tag information."""

    content: str = ""
    noindex: bool = False
    nofollow: bool = False


class XRobotsTag(BaseModel):
    """X-Robots-Tag header information."""

    value: str = ""
    noindex: bool = False
    nofollow: bool = False


class CrawlerStatus(BaseModel):
    """Individual crawler status with metadata."""

    status: Literal["allow", "disallow", "unspecified"]
    display: str = Field(..., description="Display name")
    vendor: str = Field(..., description="Vendor/company")
    purpose: str = Field(
        ..., description="search, training, or both",
    )


class AICrawlerAccess(BaseModel):
    """AI crawler access status (v3.0 — 14 crawlers)."""

    robots_txt_found: bool
    crawlers: dict[str, CrawlerStatus] = Field(
        default_factory=dict,
        description="All crawler statuses with metadata",
    )
    meta_robots: MetaRobots
    x_robots_tag: XRobotsTag
    notes: str = ""
    # Legacy flat keys for backward compatibility
    gptbot: Literal["allow", "disallow", "unspecified"] = "unspecified"
    claudebot: Literal["allow", "disallow", "unspecified"] = "unspecified"
    perplexitybot: Literal["allow", "disallow", "unspecified"] = "unspecified"
    google_extended: Literal["allow", "disallow", "unspecified"] = "unspecified"


# === Extended Metrics Models ===


class QAStructure(BaseModel):
    """Q&A structure detection results."""

    has_qa_structure: bool
    question_headings: int
    question_paragraphs: int


class LinkQuality(BaseModel):
    """Link quality assessment."""

    total_links: int
    internal_links: int
    external_links: int
    descriptive_anchors: int
    quality_score: int = Field(..., ge=0, le=3)


class ContentDepth(BaseModel):
    """Content depth assessment."""

    word_count: int
    unique_heading_levels: int
    has_deep_hierarchy: bool
    depth_score: int


class FirstParagraph(BaseModel):
    """First paragraph assessment."""

    has_strong_opening: bool
    first_paragraph_length: int
    score: int


class PronounClarity(BaseModel):
    """Pronoun clarity assessment."""

    paragraphs_starting_with_pronoun: int
    total_pronouns_in_first_10: int
    score: int


class CitationPotential(BaseModel):
    """Citation potential assessment."""

    score: int
    max_score: int
    level: Literal["high", "medium", "low", "minimal"]
    signals: list[str]


class FreshnessAssessment(BaseModel):
    """Content freshness assessment."""

    date_published: str = ""
    date_modified: str = ""
    has_dates: bool = False
    score: int = 0
    max_score: int = 4


class EEATAssessment(BaseModel):
    """E-E-A-T signal assessment."""

    author_name: str = ""
    score: int = 0
    max_score: int = 6
    signals: list[str] = Field(default_factory=list)


class ImageQualityAssessment(BaseModel):
    """Image alt text quality assessment."""

    total_images: int = 0
    alt_coverage: float = 1.0
    descriptive_ratio: float = 1.0
    score: int = 0
    max_score: int = 3


class LlmsTxtAssessment(BaseModel):
    """llms.txt presence assessment."""

    found: bool = False
    path: str = ""
    score: int = 0
    max_score: int = 2


class CitationCoverage(BaseModel):
    """Citation simulation coverage."""

    score: int = 0
    max_score: int = 7
    readiness: str = "minimal"
    signals: list[str] = Field(default_factory=list)


class CitationSimulation(BaseModel):
    """AI Citation Simulation result."""

    mode: str = "rule_based"
    mock_query: str = ""
    cited_snippets: list[dict[str, Any]] = Field(
        default_factory=list,
    )
    citation_preview: str = ""
    coverage: CitationCoverage | None = None


class ExtendedMetrics(BaseModel):
    """Extended analysis metrics (v3.0)."""

    qa_structure: QAStructure
    link_quality: LinkQuality
    content_depth: ContentDepth
    entity_count: int
    first_paragraph: FirstParagraph
    pronoun_clarity: PronounClarity
    citation_potential: CitationPotential
    # Phase 3: New signals
    freshness: FreshnessAssessment | None = None
    eeat: EEATAssessment | None = None
    image_quality: ImageQualityAssessment | None = None
    llms_txt: LlmsTxtAssessment | None = None
    # Phase 4: Citation simulation
    citation_simulation: CitationSimulation | None = None


# === Main Response Models ===


class GeoAnalysisResult(BaseModel):
    """Complete GEO analysis result."""

    geo_score: GeoScore
    summary: Summary
    ai_crawler_access: AICrawlerAccess
    extended_metrics: ExtendedMetrics

    # Optional detailed data
    ai_usage_interpretation: dict[str, Any] | None = None
    last_mile_blockers: list[str] | None = None
    structural_fixes: list[dict[str, Any]] | None = None


class JobResponse(BaseModel):
    """Response for job status and results."""

    job_id: str = Field(..., description="Unique job identifier")
    status: Literal["pending", "processing", "completed", "failed"] = Field(
        ..., description="Job status"
    )
    url: str = Field(..., description="URL being analyzed")
    created_at: datetime = Field(..., description="When job was created")
    completed_at: datetime | None = Field(
        default=None, description="When job completed"
    )
    result: GeoAnalysisResult | None = Field(
        default=None, description="Analysis result (when completed)"
    )
    error: str | None = Field(default=None, description="Error message (when failed)")

    model_config = {
        "json_schema_extra": {
            "example": {
                "job_id": "abc123def456789012345678901234",
                "status": "completed",
                "url": "https://example.com/article",
                "created_at": "2024-01-15T10:30:00Z",
                "completed_at": "2024-01-15T10:30:12Z",
                "result": {
                    "geo_score": {
                        "total": 78,
                        "grade": "B",
                        "grade_label": "good",
                        "breakdown": {
                            "accessibility": {"score": 35, "max": 40, "percentage": 88},
                            "structure": {"score": 22, "max": 30, "percentage": 73},
                            "quality": {"score": 21, "max": 30, "percentage": 70},
                        },
                    }
                },
            }
        }
    }


class HealthResponse(BaseModel):
    """Health check response."""

    status: Literal["healthy", "degraded", "unhealthy"]
    version: str
    timestamp: datetime
    checks: dict[str, bool] = Field(
        default_factory=dict, description="Individual health check results"
    )
