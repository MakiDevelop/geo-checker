"""Monitoring configuration endpoints."""
from __future__ import annotations

import sys
from typing import Literal
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, HttpUrl

from app.api.services.auth import api_key_manager
from app.api.v1.deps import check_rate_limit, require_api_key
from src.config.settings import settings
from src.db.store import (
    get_conn,
    get_url_monitoring,
    init_db,
    update_url_monitoring_with_audit,
    upsert_url,
)
from src.scheduler.rescan_scheduler import run_due_scans
from src.security.url_guard import (
    WebhookValidationError,
    resolve_webhook_target,
    validate_webhook_url,
)

router = APIRouter(tags=["Monitoring"])

CronLiteral = Literal["", "hourly", "daily", "weekly"]


class MonitoringConfig(BaseModel):
    url: HttpUrl
    rescan_cron: CronLiteral = ""
    webhook_url: str = ""
    alert_threshold: int = Field(default=0, ge=0, le=100)


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def _log_report_only(message: str) -> None:
    print(f"[webhook-guard] {message}", file=sys.stderr)


def _can_bypass_blocked_webhook(webhook_url: str) -> bool:
    try:
        resolve_webhook_target(webhook_url, allow_unsafe_network=True)
    except WebhookValidationError:
        return False
    return True


@router.put("/monitoring")
async def set_monitoring(
    request: Request,
    payload: MonitoringConfig,
    api_key: str | None = Depends(require_api_key),
) -> dict:
    """Set rescan schedule and webhook configuration for a URL."""
    await check_rate_limit(request, api_key)

    guard_reason = ""
    guard_mode = settings.security.webhook_guard_mode
    if payload.webhook_url:
        is_valid, guard_reason = validate_webhook_url(payload.webhook_url)
        if not is_valid:
            can_bypass = guard_mode in {"report_only", "off"} and _can_bypass_blocked_webhook(
                payload.webhook_url,
            )
            if not can_bypass:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error": {
                            "code": "INVALID_WEBHOOK_URL",
                            "message": guard_reason,
                        }
                    },
                )
            if guard_mode == "report_only":
                _log_report_only(
                    "report_only accepted blocked monitoring webhook for "
                    f"{payload.url}: {guard_reason}",
                )

    normalized_url = str(payload.url)
    actor = api_key_manager.validate(api_key) if api_key else None
    conn = get_conn()
    try:
        init_db(conn)
        url_id = upsert_url(conn, normalized_url)
        update_url_monitoring_with_audit(
            conn,
            normalized_url,
            rescan_cron=payload.rescan_cron,
            webhook_url=payload.webhook_url,
            alert_threshold=payload.alert_threshold,
            actor_key_name=actor.name if actor else "",
            actor_tier=actor.tier if actor else "",
            client_ip=_get_client_ip(request),
            action="update_monitoring",
            reason=guard_reason if guard_mode == "report_only" else "",
        )
        config = get_url_monitoring(conn, normalized_url)
    finally:
        conn.close()

    return {"url": normalized_url, "url_id": url_id, "config": config}


@router.get("/monitoring/{url:path}")
async def get_monitoring(
    request: Request,
    url: str,
    api_key: str | None = Depends(require_api_key),
) -> dict:
    """Return monitoring configuration for a tracked URL."""
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
    api_key: str | None = Depends(require_api_key),
) -> dict:
    """Trigger all currently due rescans."""
    await check_rate_limit(request, api_key)

    return {"triggered": run_due_scans()}
