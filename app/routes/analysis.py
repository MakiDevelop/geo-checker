"""Web UI routes."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.i18n import get_translations
from src.fetcher.html_fetcher import fetch_html
from src.geo.geo_checker import check_geo
from src.parser.content_parser import parse_content

RESULTS_DIR = Path("data/results")
TEMPLATES = Jinja2Templates(directory="app/templates")

# CSRF token configuration
# Use environment variable or generate a persistent key
# In production, set GEO_CHECKER_SECRET_KEY environment variable
_SECRET_KEY = os.environ.get("GEO_CHECKER_SECRET_KEY", "geo-checker-dev-key-change-in-production")
_CSRF_TOKEN_EXPIRY = 3600  # 1 hour


def _generate_csrf_token() -> str:
    """Generate a signed CSRF token that can be validated across workers.

    Token format: timestamp.signature
    - timestamp: Unix timestamp when token was created
    - signature: HMAC-SHA256 of timestamp using secret key
    """
    timestamp = str(int(time.time()))
    signature = hmac.new(
        _SECRET_KEY.encode(),
        timestamp.encode(),
        hashlib.sha256
    ).hexdigest()
    return f"{timestamp}.{signature}"


def _validate_csrf_token(token: str) -> bool:
    """Validate a CSRF token.

    Returns True if:
    - Token format is valid
    - Signature matches
    - Token is not expired
    """
    if not token or "." not in token:
        return False

    try:
        timestamp_str, signature = token.rsplit(".", 1)
        timestamp = int(timestamp_str)
    except (ValueError, AttributeError):
        return False

    # Check if token is expired
    current_time = int(time.time())
    if current_time - timestamp > _CSRF_TOKEN_EXPIRY:
        return False

    # Verify signature
    expected_signature = hmac.new(
        _SECRET_KEY.encode(),
        timestamp_str.encode(),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(signature, expected_signature)

router = APIRouter()


def _validate_result_id(result_id: str) -> bool:
    """Validate result_id is a valid hex UUID (32 hex chars)."""
    return bool(re.match(r"^[a-f0-9]{32}$", result_id))


def _get_safe_result_path(result_id: str) -> Path | None:
    """Get result file path with path traversal protection."""
    if not _validate_result_id(result_id):
        return None

    path = (RESULTS_DIR / f"{result_id}.json").resolve()

    # Ensure path is within RESULTS_DIR (prevent path traversal)
    try:
        path.relative_to(RESULTS_DIR.resolve())
    except ValueError:
        return None

    return path


def _sentence_excerpt(text: str, max_sentences: int = 2) -> str:
    if not text:
        return ""
    separators = [".", "。", "！", "!", "？", "?"]
    sentences = [text]
    for sep in separators:
        split = []
        for chunk in sentences:
            parts = [part.strip() for part in chunk.split(sep) if part.strip()]
            for part in parts:
                split.append(f"{part}{sep}")
        if split:
            sentences = split
    excerpt = " ".join(sentences[:max_sentences]).strip()
    return excerpt if excerpt else text.strip()


def _representative_excerpts(result: dict) -> list[str]:
    paragraphs = result.get("content", {}).get("paragraphs", [])
    excerpts = []
    for paragraph in paragraphs[:2]:
        excerpt = _sentence_excerpt(paragraph)
        if excerpt:
            excerpts.append(excerpt)
    return excerpts


def _build_llm_input(result: dict) -> dict:
    content = result.get("content", {})
    headings = [
        {"level": item.get("level", ""), "text": item.get("text", "")}
        for item in content.get("headings", [])
    ]
    paragraphs = [
        {"text": text, "role": "descriptive"}
        for text in content.get("paragraphs", [])
    ]
    return {
        "page": {
            "url": result.get("url", ""),
            "title": result.get("meta", {}).get("title", ""),
            "description": result.get("meta", {}).get("description", ""),
            "canonical": result.get("meta", {}).get("canonical", ""),
            "language": "",
        },
        "content_surfaces": {
            "headings": headings,
            "paragraphs": paragraphs,
            "lists": content.get("lists", []),
            "tables": content.get("tables", []),
        },
        "definitions": [],
        "entities": result.get("entities", []),
        "metadata": {
            "extracted_at": result.get("created_at", ""),
            "generator": "seo-geo-checker",
        },
    }


@router.get("/")
def index(request: Request) -> object:
    # Generate signed CSRF token (works across multiple workers)
    csrf_token = _generate_csrf_token()

    return TEMPLATES.TemplateResponse(
        "index.html",
        {"request": request, "t": get_translations(request), "csrf_token": csrf_token},
    )


@router.post("/analyze")
def analyze(
    request: Request,
    url: str = Form(...),
    csrf_token: str = Form(""),
) -> object:
    # CSRF protection using signed tokens (works across multiple workers)
    # Redirect to home with message if expired (better UX than 403)
    if not _validate_csrf_token(csrf_token):
        return RedirectResponse(url="/?expired=1", status_code=303)

    try:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        result_id = uuid4().hex
        html = fetch_html(url)
        result = parse_content(html, url)
        result["geo"] = check_geo(result, html, url)
        result["analysis_id"] = result_id
        result["created_at"] = datetime.now(UTC).isoformat()
        (RESULTS_DIR / f"{result_id}.json").write_text(
            json.dumps(result, ensure_ascii=True, indent=2)
        )
        return RedirectResponse(url=f"/results/{result_id}", status_code=303)
    except Exception as e:
        # Return error page instead of 500
        error_message = str(e)
        if "SSL" in error_message or "certificate" in error_message.lower():
            error_message = f"SSL certificate error for {url}. The target site may have an invalid certificate."
        elif "Connection" in error_message or "Timeout" in error_message:
            error_message = f"Could not connect to {url}. Please check if the URL is accessible."
        else:
            error_message = f"Failed to analyze {url}: {error_message}"

        return TEMPLATES.TemplateResponse(
            "index.html",
            {
                "request": request,
                "t": get_translations(request),
                "csrf_token": _generate_csrf_token(),
                "error": error_message,
            },
        )


@router.get("/results/{result_id}")
def results(request: Request, result_id: str) -> object:
    # Path traversal protection
    path = _get_safe_result_path(result_id)
    if path is None or not path.exists():
        return TEMPLATES.TemplateResponse(
            "results.html",
            {
                "request": request,
                "result": None,
                "result_id": result_id,
                "t": get_translations(request),
            },
        )
    result = json.loads(path.read_text())
    excerpts = _representative_excerpts(result)
    return TEMPLATES.TemplateResponse(
        "results.html",
        {
            "request": request,
            "result": result,
            "result_id": result_id,
            "excerpts": excerpts,
            "t": get_translations(request),
        },
    )


@router.get("/history")
def history(request: Request) -> object:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    items = sorted(RESULTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    history_items = []
    for path in items[:20]:
        data = json.loads(path.read_text())
        surface = data.get("content_surface_size", {})
        score = surface.get("score")
        history_items.append({
            "id": data.get("analysis_id", path.stem),
            "target": data.get("url", ""),
            "created_at": data.get("created_at", ""),
            "surface_score": score,
        })
    return TEMPLATES.TemplateResponse(
        "history.html", {"request": request, "items": history_items, "t": get_translations(request)}
    )


@router.get("/results/{result_id}/input.json")
def download_input(request: Request, result_id: str) -> Response:
    # Path traversal protection
    path = _get_safe_result_path(result_id)
    if path is None or not path.exists():
        return Response(status_code=404)
    result = json.loads(path.read_text())
    payload = _build_llm_input(result)
    data = json.dumps(payload, ensure_ascii=False, indent=2)
    # Header injection protection: sanitize filename
    safe_filename = quote(result_id, safe="")
    headers = {
        "Content-Disposition": f"attachment; filename={safe_filename}.json"
    }
    return Response(content=data, media_type="application/json", headers=headers)


@router.get("/robots.txt")
def robots_txt() -> Response:
    content = """# GEO Checker - AI Crawler Access
# Allow all AI crawlers to index this site

User-agent: GPTBot
Allow: /

User-agent: ClaudeBot
Allow: /

User-agent: PerplexityBot
Allow: /

User-agent: Google-Extended
Allow: /

User-agent: *
Allow: /

Sitemap: https://gc.ranran.tw/sitemap.xml
"""
    return Response(content=content, media_type="text/plain")


@router.get("/sitemap.xml")
def sitemap_xml() -> Response:
    content = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://gc.ranran.tw/</loc>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>https://gc.ranran.tw/history</loc>
    <changefreq>daily</changefreq>
    <priority>0.8</priority>
  </url>
</urlset>
"""
    return Response(content=content, media_type="application/xml")

@router.get("/terms")
def terms(request: Request) -> object:
    return TEMPLATES.TemplateResponse(
        "terms.html", {"request": request, "t": get_translations(request)}
    )


@router.get("/privacy")
def privacy(request: Request) -> object:
    return TEMPLATES.TemplateResponse(
        "privacy.html", {"request": request, "t": get_translations(request)}
    )


@router.get("/compare")
def compare_page(request: Request) -> object:
    """Render the compare input page."""
    csrf_token = _generate_csrf_token()
    return TEMPLATES.TemplateResponse(
        "compare.html",
        {"request": request, "t": get_translations(request), "csrf_token": csrf_token},
    )


@router.post("/compare")
def compare_submit(
    request: Request,
    url1: str = Form(...),
    url2: str = Form(...),
    url3: str = Form(""),
    csrf_token: str = Form(""),
) -> object:
    """Run comparison and show results."""
    from src.geo.comparator import compare_results, get_comparison_insights

    # CSRF validation
    if not _validate_csrf_token(csrf_token):
        return RedirectResponse(url="/compare?expired=1", status_code=303)

    # Collect URLs
    urls = [
        {"id": "u1", "url": url1},
        {"id": "u2", "url": url2},
    ]
    if url3 and url3.strip():
        urls.append({"id": "u3", "url": url3})

    # Run analysis on each URL
    results = {}
    errors = {}

    for item in urls:
        try:
            html = fetch_html(item["url"])
            parsed = parse_content(html, item["url"])
            geo = check_geo(parsed, html, item["url"])
            results[item["id"]] = {
                "url": item["url"],
                "geo": geo,
                "stats": parsed.get("stats", {}),
                "readability": parsed.get("readability", {}),
                "schema_org": parsed.get("schema_org", {}),
            }
        except Exception as e:
            errors[item["id"]] = str(e)

    # Check if we have enough results
    if len(results) < 2:
        return TEMPLATES.TemplateResponse(
            "compare.html",
            {
                "request": request,
                "t": get_translations(request),
                "csrf_token": _generate_csrf_token(),
                "error": "Could not analyze enough URLs. Please check the URLs and try again.",
                "errors": errors,
            },
        )

    # Generate comparison
    comparison = compare_results(results)
    insights = get_comparison_insights(comparison)

    # Save comparison
    comparison_id = uuid4().hex
    comparison_data = {
        "comparison_id": comparison_id,
        "created_at": datetime.now(UTC).isoformat(),
        "urls": {item["id"]: item["url"] for item in urls},
        "results": results,
        "comparison": comparison,
        "insights": insights,
        "errors": errors if errors else None,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / f"compare_{comparison_id}.json").write_text(
        json.dumps(comparison_data, ensure_ascii=True, indent=2, default=str)
    )

    return TEMPLATES.TemplateResponse(
        "compare-results.html",
        {
            "request": request,
            "t": get_translations(request),
            "comparison_id": comparison_id,
            "urls": {item["id"]: item["url"] for item in urls},
            "results": results,
            "comparison": comparison,
            "insights": insights,
            "errors": errors if errors else None,
        },
    )


@router.get("/compare/{comparison_id}")
def compare_results_page(request: Request, comparison_id: str) -> object:
    """Display a saved comparison result."""
    # Validate comparison_id format
    if not re.match(r"^[a-f0-9]{32}$", comparison_id):
        return TEMPLATES.TemplateResponse(
            "compare-results.html",
            {
                "request": request,
                "t": get_translations(request),
                "comparison_id": comparison_id,
                "error": "Comparison not found",
            },
        )

    path = RESULTS_DIR / f"compare_{comparison_id}.json"
    if not path.exists():
        return TEMPLATES.TemplateResponse(
            "compare-results.html",
            {
                "request": request,
                "t": get_translations(request),
                "comparison_id": comparison_id,
                "error": "Comparison not found",
            },
        )

    data = json.loads(path.read_text())
    return TEMPLATES.TemplateResponse(
        "compare-results.html",
        {
            "request": request,
            "t": get_translations(request),
            "comparison_id": comparison_id,
            "urls": data.get("urls", {}),
            "results": data.get("results", {}),
            "comparison": data.get("comparison", {}),
            "insights": data.get("insights", []),
            "errors": data.get("errors"),
        },
    )
