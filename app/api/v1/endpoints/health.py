"""Health check endpoint."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from app.api.models.responses import HealthResponse

router = APIRouter(tags=["Health"])

VERSION = "2.1.0"


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Check API health and service status.",
)
async def health_check() -> HealthResponse:
    """Return API health status."""
    checks: dict[str, bool] = {}
    overall_status = "healthy"

    # Check spaCy availability
    try:
        import spacy  # noqa: F401

        checks["nlp_spacy"] = True
    except ImportError:
        checks["nlp_spacy"] = False
        overall_status = "degraded"

    # Check textstat availability
    try:
        import textstat  # noqa: F401

        checks["nlp_textstat"] = True
    except ImportError:
        checks["nlp_textstat"] = False
        overall_status = "degraded"

    # Check extruct availability
    try:
        import extruct  # noqa: F401

        checks["schema_extractor"] = True
    except ImportError:
        checks["schema_extractor"] = False
        overall_status = "degraded"

    # Check job queue
    from app.api.services.job_queue import job_queue

    checks["job_queue"] = job_queue is not None

    return HealthResponse(
        status=overall_status,
        version=VERSION,
        timestamp=datetime.now(UTC),
        checks=checks,
    )
