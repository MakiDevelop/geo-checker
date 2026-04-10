"""Live AI Probe endpoint. BYOK — no key storage."""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel

from app.api.models.errors import ErrorCodes, ErrorResponse
from app.api.services.job_queue import job_queue
from src.ai.live_probe import generate_probe_queries, probe_perplexity

router = APIRouter(tags=["Probe"])

RESULTS_DIR = Path("data/results")
HEX_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


class ProbeRequest(BaseModel):
    job_id: str | None = None
    result_id: str | None = None
    queries: list[str] | None = None


@router.post(
    "/probe",
    responses={
        400: {"model": ErrorResponse, "description": "Invalid probe request"},
        404: {"model": ErrorResponse, "description": "Job or result not found"},
        409: {"model": ErrorResponse, "description": "Job is not ready for probing"},
        502: {"model": ErrorResponse, "description": "Probe provider failed"},
    },
    summary="Run a live AI citation probe",
)
async def run_probe(
    request: Request,
    payload: ProbeRequest,
    x_perplexity_key: str = Header(..., alias="X-Perplexity-Key"),
) -> dict[str, Any]:
    """
    執行 Live AI Probe。

    必須二選一提供 job_id 或 result_id。

    ⚠️ SECURITY:
    - X-Perplexity-Key 僅用於呼叫 Perplexity API
    - 禁止 logging / 禁止寫 DB / 禁止寫檔 / 禁止 echo 回 response
    """
    del request

    if not x_perplexity_key.startswith("pplx-"):
        raise _http_error(
            status.HTTP_400_BAD_REQUEST,
            ErrorCodes.INVALID_KEY_FORMAT,
            "Perplexity API key must start with pplx-",
        )

    has_job_id = bool(payload.job_id)
    has_result_id = bool(payload.result_id)
    if not has_job_id and not has_result_id:
        raise _http_error(
            status.HTTP_400_BAD_REQUEST,
            ErrorCodes.MISSING_IDENTIFIER,
            "Provide either job_id or result_id",
        )
    if has_job_id and has_result_id:
        raise _http_error(
            status.HTTP_400_BAD_REQUEST,
            ErrorCodes.INVALID_REQUEST,
            "Provide only one of job_id or result_id",
        )

    if payload.job_id:
        target_url, parsed = _load_job_snapshot(payload.job_id)
    else:
        assert payload.result_id is not None
        target_url, parsed = _load_result_snapshot(payload.result_id)

    queries = payload.queries or generate_probe_queries(parsed, limit=3)
    result = probe_perplexity(target_url, queries, x_perplexity_key)

    if result.error:
        raise _http_error(
            status.HTTP_502_BAD_GATEWAY,
            ErrorCodes.PROBE_FAILED,
            result.error,
            {"engine": result.engine},
        )

    response = asdict(result)
    response.pop("error", None)
    return response


def _coerce_probe_snapshot(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    parsed_snapshot = data.get("parsed_snapshot")
    if isinstance(parsed_snapshot, dict):
        snapshot = dict(parsed_snapshot)
    else:
        snapshot = {
            "url": data.get("url", ""),
            "meta": data.get("meta", {}),
            "content": data.get("content", {}),
            "entities": data.get("entities", []),
            "stats": data.get("stats", {}),
            "readability": data.get("readability", {}),
            "schema_org": data.get("schema_org", {}),
            "quotable_sentences": data.get("quotable_sentences", []),
            "freshness": data.get("freshness", {}),
            "author_info": data.get("author_info", {}),
        }

    snapshot.setdefault("meta", {})
    snapshot.setdefault("content", {})
    snapshot.setdefault("entities", data.get("entities", []))
    snapshot.setdefault("stats", data.get("stats", {}))
    snapshot.setdefault("readability", data.get("readability", {}))
    snapshot.setdefault("schema_org", data.get("schema_org", {}))
    snapshot.setdefault("quotable_sentences", data.get("quotable_sentences", []))
    snapshot.setdefault("freshness", data.get("freshness", {}))
    snapshot.setdefault("author_info", data.get("author_info", {}))

    target_url = str(snapshot.get("url") or data.get("url") or "")
    snapshot["url"] = target_url
    return target_url, snapshot


def _get_safe_result_path(result_id: str) -> Path | None:
    if not HEX_ID_PATTERN.fullmatch(result_id):
        return None

    path = (RESULTS_DIR / f"{result_id}.json").resolve()
    try:
        path.relative_to(RESULTS_DIR.resolve())
    except ValueError:
        return None

    return path


def _load_job_snapshot(job_id: str) -> tuple[str, dict[str, Any]]:
    if not HEX_ID_PATTERN.fullmatch(job_id):
        raise _http_error(
            status.HTTP_400_BAD_REQUEST,
            ErrorCodes.INVALID_REQUEST,
            "Invalid job ID format. Expected 32 hex characters.",
            {"job_id": job_id},
        )

    job = job_queue.get(job_id)
    if job is None:
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            ErrorCodes.JOB_NOT_FOUND,
            f"Job not found: {job_id}",
            {"job_id": job_id},
        )

    if job.status != "completed" or not job.result:
        raise _http_error(
            status.HTTP_409_CONFLICT,
            ErrorCodes.JOB_NOT_COMPLETED,
            "Probe is only available for completed jobs.",
            {"job_id": job_id, "status": job.status},
        )

    target_url, snapshot = _coerce_probe_snapshot({**job.result, "url": job.url})
    if not target_url:
        raise _http_error(
            status.HTTP_400_BAD_REQUEST,
            ErrorCodes.INVALID_REQUEST,
            "Probe target URL is missing from the job result",
            {"job_id": job_id},
        )
    return target_url, snapshot


def _load_result_snapshot(result_id: str) -> tuple[str, dict[str, Any]]:
    path = _get_safe_result_path(result_id)
    if path is None:
        raise _http_error(
            status.HTTP_400_BAD_REQUEST,
            ErrorCodes.INVALID_REQUEST,
            "Invalid result ID format. Expected 32 hex characters.",
            {"result_id": result_id},
        )

    if not path.exists():
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            ErrorCodes.RESULT_NOT_FOUND,
            f"Result not found: {result_id}",
            {"result_id": result_id},
        )

    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        raise _http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            ErrorCodes.INTERNAL_ERROR,
            "Stored result could not be loaded",
            {"result_id": result_id},
        )

    target_url, snapshot = _coerce_probe_snapshot(payload)
    if not target_url:
        raise _http_error(
            status.HTTP_400_BAD_REQUEST,
            ErrorCodes.INVALID_REQUEST,
            "Probe target URL is missing from the stored result",
            {"result_id": result_id},
        )
    return target_url, snapshot


def _http_error(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "error": {
                "code": code,
                "message": message,
                "details": details,
            }
        },
    )
