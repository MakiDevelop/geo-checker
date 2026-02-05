"""Multi-URL comparison endpoint."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.models.errors import ErrorCodes, ErrorResponse
from app.api.models.requests import CompareRequest
from app.api.v1.deps import (
    check_rate_limit,
    get_optional_api_key,
    validate_api_key,
)
from src.fetcher.html_fetcher import fetch_html
from src.geo.comparator import compare_results, get_comparison_insights
from src.geo.geo_checker import check_geo
from src.parser.content_parser import parse_content

router = APIRouter(tags=["Comparison"])

# Results directory
RESULTS_DIR = Path("data/results")


def _run_analysis(url: str) -> dict:
    """Run GEO analysis on a single URL."""
    html = fetch_html(url)
    parsed = parse_content(html, url)
    geo = check_geo(parsed, html, url)

    return {
        "url": url,
        "geo": geo,
        "stats": parsed.get("stats", {}),
        "readability": parsed.get("readability", {}),
        "schema_org": parsed.get("schema_org", {}),
    }


@router.post(
    "/compare",
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        401: {"model": ErrorResponse, "description": "Invalid API key"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
    },
    summary="Compare multiple URLs for GEO",
    description="""
Compare 2-3 URLs side-by-side for GEO (Generative Engine Optimization).

This endpoint runs analysis on all provided URLs synchronously and returns
a comparison showing:
- GEO Score differences
- Metric-by-metric comparison
- Winner determination
- Actionable insights

**Note:** This operation is synchronous and may take 10-30 seconds depending
on the number of URLs and their response times.

**Rate Limits:**
- Anonymous: 2 requests/minute
- With API Key: 10 requests/minute
""",
)
async def compare_urls(
    request: Request,
    body: CompareRequest,
    api_key: str | None = Depends(get_optional_api_key),
) -> dict[str, Any]:
    """Compare multiple URLs for GEO optimization."""
    # Validate API key if provided
    await validate_api_key(api_key)

    # Check rate limit (stricter for comparison)
    await check_rate_limit(request, api_key)

    # Validate URLs
    for item in body.urls:
        url_str = str(item.url)
        if not url_str.startswith(("http://", "https://")):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": {
                        "code": ErrorCodes.INVALID_URL,
                        "message": f"Invalid URL scheme for {item.id}",
                        "details": {"url": url_str},
                    }
                },
            )

    # Run analysis on each URL
    results: dict[str, dict] = {}
    errors: dict[str, str] = {}

    for item in body.urls:
        url_str = str(item.url)
        try:
            result = _run_analysis(url_str)
            results[item.id] = result
        except Exception as e:
            errors[item.id] = str(e)

    # Check if we have enough results
    if len(results) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "ANALYSIS_FAILED",
                    "message": "Could not analyze enough URLs for comparison",
                    "details": {"errors": errors},
                }
            },
        )

    # Generate comparison
    comparison = compare_results(results)
    insights = get_comparison_insights(comparison)

    # Build response
    comparison_id = uuid4().hex
    response = {
        "comparison_id": comparison_id,
        "created_at": datetime.now(UTC).isoformat(),
        "urls": {item.id: str(item.url) for item in body.urls},
        "summary": comparison.get("summary", {}),
        "diffs": comparison.get("diffs", []),
        "insights": insights,
        "errors": errors if errors else None,
    }

    # Save comparison result
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    result_path = RESULTS_DIR / f"compare_{comparison_id}.json"
    result_path.write_text(json.dumps(response, indent=2, default=str))

    return response


@router.get(
    "/compare/{comparison_id}",
    responses={
        404: {"model": ErrorResponse, "description": "Comparison not found"},
    },
    summary="Get comparison result",
    description="Retrieve a previously generated comparison result by ID.",
)
async def get_comparison(comparison_id: str) -> dict[str, Any]:
    """Get a comparison result by ID."""
    # Validate comparison_id format
    if not comparison_id.isalnum() or len(comparison_id) != 32:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": "Comparison not found",
                }
            },
        )

    result_path = RESULTS_DIR / f"compare_{comparison_id}.json"
    if not result_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": "Comparison not found",
                }
            },
        )

    return json.loads(result_path.read_text())
