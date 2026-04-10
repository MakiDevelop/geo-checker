"""FastAPI entry point."""
import sys
import time
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1.router import router as api_router
from app.routes.analysis import router as analysis_router
from src.config.settings import settings
from src.db.store import (
    get_conn,
    init_db,
    log_monitoring_audit_event,
    update_url_monitoring_with_audit,
)
from src.scheduler.rescan_scheduler import start_scheduler, stop_scheduler
from src.security.url_guard import validate_webhook_url


def sanitize_existing_webhooks() -> int:
    """Remove or report invalid stored webhook URLs before the scheduler starts."""
    guard_mode = settings.security.webhook_guard_mode
    if guard_mode == "off":
        return 0

    conn = get_conn()
    try:
        init_db(conn)
        rows = conn.execute(
            """
            SELECT url, webhook_url
            FROM urls
            WHERE webhook_url IS NOT NULL AND webhook_url <> ''
            ORDER BY id ASC
            """,
        ).fetchall()

        sanitized = 0
        for row in rows:
            url = str(row["url"])
            webhook_url = str(row["webhook_url"] or "")
            try:
                is_valid, reason = validate_webhook_url(webhook_url)
                if is_valid:
                    continue

                print(
                    f"[webhook-guard] startup detected invalid stored webhook for {url}: {reason}",
                    file=sys.stderr,
                )

                if guard_mode == "report_only":
                    log_monitoring_audit_event(
                        conn,
                        url=url,
                        actor_key_name="system/backfill",
                        actor_tier="system/backfill",
                        action="sanitize_invalid_webhook",
                        old_webhook_url=webhook_url,
                        new_webhook_url=webhook_url,
                        reason=f"report_only: {reason}",
                    )
                    continue

                updated = update_url_monitoring_with_audit(
                    conn,
                    url,
                    webhook_url="",
                    actor_key_name="system/backfill",
                    actor_tier="system/backfill",
                    action="sanitize_invalid_webhook",
                    reason=reason,
                )
                if updated:
                    sanitized += 1
            except Exception as exc:
                # Never let one bad row block app startup. Log and move on so the
                # remaining rows still get sanitized; the bad row keeps its old
                # state until a later request touches it explicitly.
                print(
                    f"[webhook-guard] startup sanitize error for {url}: {exc!r}",
                    file=sys.stderr,
                )
                continue

        return sanitized
    finally:
        conn.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    conn = get_conn()
    try:
        init_db(conn)
    finally:
        conn.close()
    sanitize_existing_webhooks()
    start_scheduler()
    yield
    stop_scheduler()

# Rate limiting configuration (for web UI)
RATE_LIMIT_REQUESTS = settings.security.rate_limit_requests
RATE_LIMIT_WINDOW = settings.security.rate_limit_window


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory rate limiter by IP address (for web UI)."""

    def __init__(self, app, requests_limit: int = 10, window_seconds: int = 60):
        super().__init__(app)
        self.requests_limit = requests_limit
        self.window_seconds = window_seconds
        self.requests: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for static files and API (API has its own limiter)
        if request.url.path.startswith(("/static", "/api")):
            return await call_next(request)

        # Get client IP (consider X-Forwarded-For for reverse proxy)
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "unknown"

        now = time.time()
        window_start = now - self.window_seconds

        # Clean old requests
        self.requests[client_ip] = [
            t for t in self.requests[client_ip] if t > window_start
        ]

        # Check rate limit
        if len(self.requests[client_ip]) >= self.requests_limit:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please try again later."},
                headers={"Retry-After": str(self.window_seconds)},
            )

        # Record this request
        self.requests[client_ip].append(now)

        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    # CSP for Swagger UI / ReDoc (needs CDN resources)
    API_DOCS_CSP = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "img-src 'self' data: https://cdn.jsdelivr.net https://fastapi.tiangolo.com; "
        "font-src 'self' https://cdn.jsdelivr.net; "
        "connect-src 'self'; "
        "frame-ancestors 'none'"
    )

    # CSP for main web UI
    DEFAULT_CSP = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://www.googletagmanager.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "img-src 'self' data:; "
        "font-src 'self' https://fonts.gstatic.com; "
        "connect-src 'self' https://www.google-analytics.com; "
        "frame-ancestors 'none'"
    )

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Use relaxed CSP for API docs pages
        if request.url.path in ("/api/docs", "/api/redoc", "/api/openapi.json"):
            response.headers["Content-Security-Policy"] = self.API_DOCS_CSP
        else:
            response.headers["Content-Security-Policy"] = self.DEFAULT_CSP

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response


class APIRateLimitHeadersMiddleware(BaseHTTPMiddleware):
    """Add rate limit headers to API responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Only add headers for API routes
        if request.url.path.startswith("/api"):
            if hasattr(request.state, "rate_limit_remaining"):
                response.headers["X-RateLimit-Remaining"] = str(
                    request.state.rate_limit_remaining
                )
            if hasattr(request.state, "rate_limit_reset"):
                response.headers["X-RateLimit-Reset"] = str(
                    int(time.time()) + request.state.rate_limit_reset
                )
            if hasattr(request.state, "rate_limit_limit"):
                response.headers["X-RateLimit-Limit"] = str(
                    request.state.rate_limit_limit
                )

        return response


app = FastAPI(
    lifespan=lifespan,
    title="GEO Checker API",
    description="""
API for analyzing web pages for Generative Engine Optimization (GEO).

## Features

- **GEO Score**: 0-100 score across accessibility, structure, and quality dimensions
- **AI Crawler Access**: Check robots.txt rules for GPTBot, ClaudeBot, etc.
- **Content Analysis**: Headings, lists, tables, Schema.org markup
- **Readability Metrics**: Flesch score, reading level, content depth

## Authentication

API requests can be made:
- **Anonymous**: Lower rate limits (5 req/min)
- **With API Key**: Higher rate limits (30+ req/min)

Pass API key via `X-API-Key` header or `Authorization: Bearer <key>`.

## Async Processing

Analysis runs asynchronously:
1. `POST /api/v1/analyze` - Submit URL, get `job_id`
2. `GET /api/v1/jobs/{job_id}` - Poll for results
""",
    version="4.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# CORS middleware (for API cross-origin requests)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.api.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["X-API-Key", "X-Perplexity-Key", "Authorization", "Content-Type"],
)

# Add middlewares (order matters: outermost first)
app.add_middleware(APIRateLimitHeadersMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    RateLimitMiddleware,
    requests_limit=RATE_LIMIT_REQUESTS,
    window_seconds=RATE_LIMIT_WINDOW,
)

# Mount API router
app.include_router(api_router, prefix="/api/v1")

# Mount web UI router
app.include_router(analysis_router)

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

