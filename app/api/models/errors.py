"""API error response models."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Detailed error information."""

    code: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Human-readable error message")
    details: dict[str, Any] | None = Field(
        default=None, description="Additional error details"
    )


class ErrorResponse(BaseModel):
    """Standard error response format."""

    error: ErrorDetail

    model_config = {
        "json_schema_extra": {
            "example": {
                "error": {
                    "code": "INVALID_URL",
                    "message": "The provided URL is not accessible",
                    "details": {"url": "https://example.com", "reason": "Connection timeout"},
                }
            }
        }
    }


class ErrorCodes:
    """Standardized error codes."""

    # 4xx Client Errors
    INVALID_URL = "INVALID_URL"
    URL_NOT_ACCESSIBLE = "URL_NOT_ACCESSIBLE"
    URL_BLOCKED_SSRF = "URL_BLOCKED_SSRF"
    INVALID_REQUEST = "INVALID_REQUEST"
    INVALID_API_KEY = "INVALID_API_KEY"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"

    # 5xx Server Errors
    ANALYSIS_FAILED = "ANALYSIS_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
