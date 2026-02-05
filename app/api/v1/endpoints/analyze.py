"""Analysis submission endpoint."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.models.errors import ErrorCodes, ErrorResponse
from app.api.models.requests import AnalyzeRequest
from app.api.models.responses import JobResponse
from app.api.services.job_queue import job_queue
from app.api.v1.deps import (
    check_rate_limit,
    get_optional_api_key,
    validate_api_key,
)

router = APIRouter(tags=["Analysis"])


@router.post(
    "/analyze",
    response_model=JobResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        401: {"model": ErrorResponse, "description": "Invalid API key"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
    },
    summary="Submit URL for GEO analysis",
    description="""
Submit a URL for GEO (Generative Engine Optimization) analysis.

The analysis runs asynchronously. This endpoint returns immediately with a `job_id`.
Use `GET /api/v1/jobs/{job_id}` to poll for results.

**Analysis evaluates:**
- **Accessibility** (40%): AI crawler access, robots.txt rules, meta tags
- **Structure** (30%): Headings, lists, tables, Schema.org markup
- **Quality** (30%): Readability, entity richness, quotable content

**Rate Limits:**
- Anonymous: 5 requests/minute
- With API Key: 30 requests/minute (standard tier)
""",
)
async def submit_analysis(
    request: Request,
    body: AnalyzeRequest,
    api_key: str | None = Depends(get_optional_api_key),
) -> JobResponse:
    """Submit a URL for GEO analysis."""
    # Validate API key if provided
    await validate_api_key(api_key)

    # Check rate limit
    await check_rate_limit(request, api_key)

    # Validate URL scheme
    url_str = str(body.url)
    if not url_str.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": ErrorCodes.INVALID_URL,
                    "message": "Only http and https URLs are supported",
                    "details": {"url": url_str},
                }
            },
        )

    # Submit job
    job_id = job_queue.submit(url_str)
    job = job_queue.get(job_id)

    return JobResponse(
        job_id=job_id,
        status=job.status if job else "pending",
        url=url_str,
        created_at=job.created_at if job else datetime.now(UTC),
        completed_at=None,
        result=None,
        error=None,
    )
