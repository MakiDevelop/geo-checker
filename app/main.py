"""FastAPI entry point."""
import time
from collections import defaultdict

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1.router import router as api_router
from app.routes.analysis import router as analysis_router
from src.config.settings import settings

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
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
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
    version="2.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# CORS middleware (for API cross-origin requests)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.api.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["X-API-Key", "Authorization", "Content-Type"],
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
