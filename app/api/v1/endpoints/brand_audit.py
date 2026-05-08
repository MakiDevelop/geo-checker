"""Brand visibility audit endpoint."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, Request

from app.api.models.requests import BrandAuditRequest
from app.api.models.responses import BrandAuditResponse
from app.api.v1.deps import (
    check_rate_limit,
    get_optional_api_key,
    validate_api_key,
)
from src.geo.brand_audit import build_brand_audit

router = APIRouter(tags=["Brand Audit"])


@router.post(
    "/brand-audit",
    response_model=BrandAuditResponse,
    summary="Audit brand visibility in AI answer engines",
    description="""
Generate a CJK-first brand visibility audit for answer engines.

The endpoint does not call external AI services. It returns:
- localized prompt pack for Taiwan/Japan/global visibility checks
- target and competitor mention-rate analysis from optional pasted answers
- prioritized GEO/AIO fixes
- copy-ready Markdown report
""",
)
async def brand_audit(
    request: Request,
    body: BrandAuditRequest,
    api_key: str | None = Depends(get_optional_api_key),
) -> BrandAuditResponse:
    """Run deterministic brand visibility audit."""
    await validate_api_key(api_key)
    await check_rate_limit(request, api_key)

    audit = build_brand_audit(
        brand_name=body.brand_name,
        website_url=str(body.website_url),
        region=body.region,
        language=body.language,
        competitors=body.competitors,
        answer_texts=body.answer_texts,
        category=body.category,
        use_case=body.use_case,
    )
    payload = audit.to_dict()
    return BrandAuditResponse(
        audit_id=uuid4().hex,
        created_at=datetime.now(UTC),
        **payload,
    )
