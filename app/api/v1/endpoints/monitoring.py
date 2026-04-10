"""Monitoring configuration endpoints."""
from __future__ import annotations

from typing import Literal
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, HttpUrl

from app.api.v1.deps import check_rate_limit, get_optional_api_key, validate_api_key
from src.db.store import (
    get_conn,
    get_url_monitoring,
    init_db,
    update_url_monitoring,
    upsert_url,
)
from src.scheduler.rescan_scheduler import run_due_scans

router = APIRouter(tags=["Monitoring"])

CronLiteral = Literal["", "hourly", "daily", "weekly"]


class MonitoringConfig(BaseModel):
    url: HttpUrl
    rescan_cron: CronLiteral = ""
    webhook_url: str = ""
    alert_threshold: int = Field(default=0, ge=0, le=100)


@router.put("/monitoring")
async def set_monitoring(
    request: Request,
    payload: MonitoringConfig,
    api_key: str | None = Depends(get_optional_api_key),
) -> dict:
    """Set rescan schedule and webhook configuration for a URL."""
    await validate_api_key(api_key)
    await check_rate_limit(request, api_key)

    if payload.webhook_url and not payload.webhook_url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "INVALID_WEBHOOK_URL",
                    "message": "webhook_url must start with http:// or https://",
                }
            },
        )

    normalized_url = str(payload.url)
    conn = get_conn()
    try:
        init_db(conn)
        url_id = upsert_url(conn, normalized_url)
        update_url_monitoring(
            conn,
            normalized_url,
            rescan_cron=payload.rescan_cron,
            webhook_url=payload.webhook_url,
            alert_threshold=payload.alert_threshold,
        )
        config = get_url_monitoring(conn, normalized_url)
    finally:
        conn.close()

    return {"url": normalized_url, "url_id": url_id, "config": config}


@router.get("/monitoring/{url:path}")
async def get_monitoring(
    request: Request,
    url: str,
    api_key: str | None = Depends(get_optional_api_key),
) -> dict:
    """Return monitoring configuration for a tracked URL."""
    await validate_api_key(api_key)
    await check_rate_limit(request, api_key)

    normalized_url = unquote(url)
    conn = get_conn()
    try:
        init_db(conn)
        config = get_url_monitoring(conn, normalized_url)
    finally:
        conn.close()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "URL_NOT_TRACKED",
                    "message": f"URL not tracked: {normalized_url}",
                }
            },
        )

    return {"url": normalized_url, "config": config}


@router.post("/monitoring/run-now")
async def trigger_run_now(
    request: Request,
    api_key: str | None = Depends(get_optional_api_key),
) -> dict:
    """Trigger all currently due rescans."""
    await validate_api_key(api_key)
    await check_rate_limit(request, api_key)

    return {"triggered": run_due_scans()}
