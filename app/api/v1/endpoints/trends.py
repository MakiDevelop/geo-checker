"""Trend tracking and fix generation endpoints."""
from __future__ import annotations

import re
from dataclasses import asdict
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.models.errors import ErrorCodes
from app.api.services.job_queue import job_queue
from app.api.v1.deps import (
    check_rate_limit,
    get_optional_api_key,
    validate_api_key,
)
from src.db.store import (
    diff_scans,
    get_conn,
    get_scan_detail,
    get_url_history,
    init_db,
)
from src.toolkit.fix_generator import generate_fixes

router = APIRouter(tags=["Trends", "Fixes"])

JOB_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


@router.get("/trends/diff")
async def get_diff(
    request: Request,
    scan_a: int,
    scan_b: int,
    api_key: str | None = Depends(get_optional_api_key),
) -> dict:
    """Compare two historical scan records."""
    await validate_api_key(api_key)
    await check_rate_limit(request, api_key)

    conn = get_conn()
    try:
        init_db(conn)
        detail_a = get_scan_detail(conn, scan_a)
        detail_b = get_scan_detail(conn, scan_b)
        if detail_a is None or detail_b is None:
            missing_id = scan_a if detail_a is None else scan_b
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": {
                        "code": "SCAN_NOT_FOUND",
                        "message": f"Scan not found: {missing_id}",
                        "details": {"scan_id": missing_id},
                    }
                },
            )

        return {
            "scan_a": scan_a,
            "scan_b": scan_b,
            "url_a": detail_a["url"],
            "url_b": detail_b["url"],
            **diff_scans(conn, scan_a, scan_b),
        }
    finally:
        conn.close()


@router.get("/fixes/{job_id}")
async def get_fixes(
    request: Request,
    job_id: str,
    api_key: str | None = Depends(get_optional_api_key),
) -> dict:
    """Return copy-pasteable fixes for a completed analysis job."""
    await validate_api_key(api_key)
    await check_rate_limit(request, api_key)

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

    if job.status != "completed" or not job.result:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "JOB_NOT_COMPLETED",
                    "message": "Fixes are only available for completed jobs.",
                    "details": {"job_id": job_id, "status": job.status},
                }
            },
        )

    parsed_snapshot = job.result.get("parsed_snapshot") or _fallback_parsed_snapshot(
        job.result, job.url,
    )
    fixes = generate_fixes(
        job.result.get("geo", {}),
        parsed_snapshot,
        url=parsed_snapshot.get("url", job.url),
    )

    return {
        "job_id": job_id,
        "url": parsed_snapshot.get("url", job.url),
        "fixes": [asdict(item) for item in fixes],
    }


@router.get("/trends/{url:path}")
async def get_trends(
    request: Request,
    url: str,
    limit: int = 20,
    api_key: str | None = Depends(get_optional_api_key),
) -> dict:
    """Return historical score trends for a URL."""
    await validate_api_key(api_key)
    await check_rate_limit(request, api_key)

    normalized_url = unquote(url)
    conn = get_conn()
    try:
        init_db(conn)
        history = get_url_history(conn, normalized_url, limit=max(1, min(limit, 100)))
        if not history:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": {
                        "code": "TREND_NOT_FOUND",
                        "message": f"No scan history found for URL: {normalized_url}",
                        "details": {"url": normalized_url},
                    }
                },
            )

        return {
            "url": normalized_url,
            "count": len(history),
            "history": history,
        }
    finally:
        conn.close()


def _fallback_parsed_snapshot(result: dict, url: str) -> dict:
    return {
        "url": url,
        "meta": result.get("meta", {}),
        "content": result.get("content", {}),
        "stats": result.get("stats", {}),
        "readability": result.get("readability", {}),
        "schema_org": result.get("schema_org", {}),
        "freshness": result.get("freshness", {}),
        "author_info": result.get("author_info", {}),
    }
