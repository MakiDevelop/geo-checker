"""Job status and results endpoint."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.models.errors import ErrorCodes, ErrorResponse
from app.api.models.responses import (
    AICrawlerAccess,
    CitationPotential,
    ContentDepth,
    ExtendedMetrics,
    FirstParagraph,
    GeoAnalysisResult,
    GeoScore,
    GeoScoreBreakdown,
    Issue,
    IssuesSummary,
    JobResponse,
    LinkQuality,
    MetaRobots,
    PriorityFix,
    PronounClarity,
    QAStructure,
    ScoreBreakdownItem,
    Summary,
    XRobotsTag,
)
from app.api.services.job_queue import Job, job_queue
from app.api.v1.deps import (
    check_rate_limit,
    get_optional_api_key,
    validate_api_key,
)

router = APIRouter(tags=["Jobs"])

# Valid job ID pattern (32 hex chars)
JOB_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


def _convert_geo_result(geo: dict) -> GeoAnalysisResult:
    """Convert raw geo dict to Pydantic model."""
    # Extract geo_score
    gs = geo.get("geo_score", {})
    breakdown = gs.get("breakdown", {})

    geo_score = GeoScore(
        total=gs.get("total", 0),
        grade=gs.get("grade", "F"),
        grade_label=gs.get("grade_label", "unknown"),
        breakdown=GeoScoreBreakdown(
            accessibility=ScoreBreakdownItem(**breakdown.get("accessibility", {"score": 0, "max": 40, "percentage": 0})),
            structure=ScoreBreakdownItem(**breakdown.get("structure", {"score": 0, "max": 30, "percentage": 0})),
            quality=ScoreBreakdownItem(**breakdown.get("quality", {"score": 0, "max": 30, "percentage": 0})),
        ),
    )

    # Extract summary
    summary_data = geo.get("summary", {})
    issues_data = summary_data.get("issues", {})
    issues = IssuesSummary(
        critical=[Issue(**i) for i in issues_data.get("critical", [])],
        warning=[Issue(**i) for i in issues_data.get("warning", [])],
        good=[Issue(**i) for i in issues_data.get("good", [])],
    )
    priority_fixes = [PriorityFix(**pf) for pf in summary_data.get("priority_fixes", [])]
    summary = Summary(
        summary_key=summary_data.get("summary_key", ""),
        issues=issues,
        priority_fixes=priority_fixes,
    )

    # Extract AI crawler access
    aca = geo.get("ai_crawler_access", {})
    meta_robots = aca.get("meta_robots", {})
    x_robots = aca.get("x_robots_tag", {})
    ai_crawler_access = AICrawlerAccess(
        robots_txt_found=aca.get("robots_txt_found", False),
        gptbot=aca.get("gptbot", "unspecified"),
        claudebot=aca.get("claudebot", "unspecified"),
        perplexitybot=aca.get("perplexitybot", "unspecified"),
        google_extended=aca.get("google_extended", "unspecified"),
        meta_robots=MetaRobots(
            content=meta_robots.get("content", ""),
            noindex=meta_robots.get("noindex", False),
            nofollow=meta_robots.get("nofollow", False),
        ),
        x_robots_tag=XRobotsTag(
            value=x_robots.get("value", ""),
            noindex=x_robots.get("noindex", False),
            nofollow=x_robots.get("nofollow", False),
        ),
        notes=aca.get("notes", ""),
    )

    # Extract extended metrics
    em = geo.get("extended_metrics", {})
    qa = em.get("qa_structure", {})
    lq = em.get("link_quality", {})
    cd = em.get("content_depth", {})
    fp = em.get("first_paragraph", {})
    pc = em.get("pronoun_clarity", {})
    cp = em.get("citation_potential", {})

    extended_metrics = ExtendedMetrics(
        qa_structure=QAStructure(
            has_qa_structure=qa.get("has_qa_structure", False),
            question_headings=qa.get("question_headings", 0),
            question_paragraphs=qa.get("question_paragraphs", 0),
        ),
        link_quality=LinkQuality(
            total_links=lq.get("total_links", 0),
            internal_links=lq.get("internal_links", 0),
            external_links=lq.get("external_links", 0),
            descriptive_anchors=lq.get("descriptive_anchors", 0),
            quality_score=lq.get("quality_score", 0),
        ),
        content_depth=ContentDepth(
            word_count=cd.get("word_count", 0),
            unique_heading_levels=cd.get("unique_heading_levels", 0),
            has_deep_hierarchy=cd.get("has_deep_hierarchy", False),
            depth_score=cd.get("depth_score", 0),
        ),
        entity_count=em.get("entity_count", 0),
        first_paragraph=FirstParagraph(
            has_strong_opening=fp.get("has_strong_opening", False),
            first_paragraph_length=fp.get("first_paragraph_length", 0),
            score=fp.get("score", 0),
        ),
        pronoun_clarity=PronounClarity(
            paragraphs_starting_with_pronoun=pc.get("paragraphs_starting_with_pronoun", 0),
            total_pronouns_in_first_10=pc.get("total_pronouns_in_first_10", 0),
            score=pc.get("score", 0),
        ),
        citation_potential=CitationPotential(
            score=cp.get("score", 0),
            max_score=cp.get("max_score", 11),
            level=cp.get("level", "minimal"),
            signals=cp.get("signals", []),
        ),
    )

    return GeoAnalysisResult(
        geo_score=geo_score,
        summary=summary,
        ai_crawler_access=ai_crawler_access,
        extended_metrics=extended_metrics,
        ai_usage_interpretation=geo.get("ai_usage_interpretation"),
        last_mile_blockers=geo.get("last_mile_blockers"),
        structural_fixes=geo.get("structural_fixes"),
    )


def _job_to_response(job: Job) -> JobResponse:
    """Convert Job to JobResponse."""
    result = None
    if job.status == "completed" and job.result:
        geo = job.result.get("geo", {})
        result = _convert_geo_result(geo)

    return JobResponse(
        job_id=job.id,
        status=job.status,
        url=job.url,
        created_at=job.created_at,
        completed_at=job.completed_at,
        result=result,
        error=job.error,
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid job ID format"},
        404: {"model": ErrorResponse, "description": "Job not found"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
    },
    summary="Get job status and results",
    description="""
Retrieve the status and results of an analysis job.

**Status values:**
- `pending`: Job is queued
- `processing`: Analysis is running
- `completed`: Analysis finished successfully (result available)
- `failed`: Analysis failed (error message available)

Poll this endpoint until status is `completed` or `failed`.
""",
)
async def get_job(
    request: Request,
    job_id: str,
    api_key: str | None = Depends(get_optional_api_key),
) -> JobResponse:
    """Get job status and results by ID."""
    # Validate API key if provided
    await validate_api_key(api_key)

    # Check rate limit
    await check_rate_limit(request, api_key)

    # Validate job ID format
    if not JOB_ID_PATTERN.match(job_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": ErrorCodes.INVALID_REQUEST,
                    "message": "Invalid job ID format. Expected 32 hex characters.",
                    "details": {"job_id": job_id},
                }
            },
        )

    # Get job
    job = job_queue.get(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": ErrorCodes.JOB_NOT_FOUND,
                    "message": f"Job not found: {job_id}",
                    "details": {"job_id": job_id},
                }
            },
        )

    return _job_to_response(job)
