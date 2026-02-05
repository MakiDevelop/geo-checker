"""API dependencies for authentication and rate limiting."""
from __future__ import annotations

import time

from cachetools import TTLCache
from fastapi import Header, HTTPException, Request, status

from app.api.models.errors import ErrorCodes
from app.api.services.auth import api_key_manager
from src.config.settings import settings


class APIRateLimiter:
    """Rate limiter for API endpoints with automatic TTL-based cleanup."""

    def __init__(self, max_identifiers: int = 10000):
        # TTL = 2x rate limit window to ensure entries live long enough
        # Max 10k identifiers to cap memory usage
        ttl = settings.api.rate_limit_window * 2
        self._requests: TTLCache[str, list[float]] = TTLCache(
            maxsize=max_identifiers, ttl=ttl
        )

    def _get_identifier(self, request: Request, api_key: str | None) -> str:
        """Get rate limit identifier (key prefix or IP)."""
        if api_key:
            # Use first 8 chars of key hash for identification
            return f"key:{api_key[:16]}"

        # Fall back to IP address
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "unknown"

        return f"ip:{client_ip}"

    def check(
        self,
        request: Request,
        api_key: str | None,
    ) -> tuple[bool, int, int]:
        """
        Check if request is within rate limit.

        Returns:
            (allowed, remaining, reset_seconds)
        """
        identifier = self._get_identifier(request, api_key)
        limit = api_key_manager.get_rate_limit(api_key)
        window = settings.api.rate_limit_window

        now = time.time()
        window_start = now - window

        # Get existing requests or empty list
        requests = self._requests.get(identifier, [])

        # Clean old requests within window
        requests = [t for t in requests if t > window_start]

        current_count = len(requests)
        remaining = max(0, limit - current_count - 1)

        if current_count >= limit:
            # Calculate reset time from oldest request in window
            oldest = min(requests) if requests else now
            reset_seconds = int(oldest + window - now)
            # Update cache with cleaned list
            self._requests[identifier] = requests
            return False, 0, max(1, reset_seconds)

        # Record this request and update cache
        requests.append(now)
        self._requests[identifier] = requests
        return True, remaining, window


# Global rate limiter instance
api_rate_limiter = APIRateLimiter()


async def get_optional_api_key(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    authorization: str | None = Header(None),
) -> str | None:
    """Extract optional API key from headers.

    Supports:
        - X-API-Key header
        - Authorization: Bearer <key>
    """
    # Try X-API-Key header first
    if x_api_key:
        return x_api_key

    # Try Authorization: Bearer <key>
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()

    return None


async def validate_api_key(
    api_key: str | None,
) -> str | None:
    """Validate API key if provided.

    Returns the key if valid, None if not provided.
    Raises HTTPException if key is provided but invalid.
    """
    if not api_key:
        return None

    info = api_key_manager.validate(api_key)
    if not info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": ErrorCodes.INVALID_API_KEY,
                    "message": "The provided API key is invalid.",
                }
            },
        )

    return api_key


async def check_rate_limit(
    request: Request,
    api_key: str | None,
) -> None:
    """Check and enforce API rate limits.

    Adds rate limit info to request.state for response headers.
    Raises HTTPException if rate limit exceeded.
    """
    allowed, remaining, reset = api_rate_limiter.check(request, api_key)

    # Store for response headers
    request.state.rate_limit_remaining = remaining
    request.state.rate_limit_reset = reset
    request.state.rate_limit_limit = api_key_manager.get_rate_limit(api_key)

    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": {
                    "code": ErrorCodes.RATE_LIMIT_EXCEEDED,
                    "message": "Too many requests. Please slow down.",
                    "details": {
                        "retry_after": reset,
                        "limit": api_key_manager.get_rate_limit(api_key),
                    },
                }
            },
            headers={
                "Retry-After": str(reset),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(time.time()) + reset),
            },
        )
