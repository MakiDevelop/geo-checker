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
from src.db.store import get_conn, get_url_history, init_db, save_scan, upsert_url
from src.fetcher.ghost_fetcher import is_ghost_url
from src.fetcher.html_fetcher import fetch_html
from src.geo.geo_checker import check_geo
from src.parser.content_parser import parse_content
from src.toolkit.badge import generate_badge_svg
from src.toolkit.checklist import generate_checklist
from src.toolkit.fix_generator import generate_fixes
from src.toolkit.robots_generator import generate_robots_txt
from src.toolkit.schema_generator import (
    generate_all_schemas,
    schemas_to_html,
)
from src.toolkit.score_card import generate_card_image_sync

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


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _extract_result_score(data: dict) -> int | None:
    geo_score = data.get("geo", {}).get("geo_score", {})
    if geo_score.get("total") is not None:
        return int(geo_score.get("total", 0))
    surface = data.get("content_surface_size", {})
    if surface.get("score") is not None:
        return int(surface.get("score", 0))
    return None


def _extract_result_grade(data: dict) -> str:
    return str(data.get("geo", {}).get("geo_score", {}).get("grade", ""))


def _load_json_result_records() -> list[dict]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    records = []

    for path in RESULTS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue

        scanned_at = str(data.get("created_at", ""))
        parsed_dt = _parse_timestamp(scanned_at)
        if parsed_dt is None:
            parsed_dt = datetime.fromtimestamp(path.stat().st_mtime, UTC)

        records.append(
            {
                "result_id": str(data.get("analysis_id", path.stem)),
                "url": str(data.get("url", "")),
                "total_score": _extract_result_score(data),
                "grade": _extract_result_grade(data),
                "scanned_at": scanned_at,
                "_parsed_dt": parsed_dt,
            }
        )

    records.sort(key=lambda item: item["_parsed_dt"], reverse=True)
    return records


def _get_json_url_history(url: str, *, limit: int = 20) -> list[dict]:
    if not url:
        return []

    history = []
    for item in _load_json_result_records():
        if item["url"] != url:
            continue
        if item["total_score"] is None:
            continue
        history.append(
            {
                "scan_id": item["result_id"],
                "result_id": item["result_id"],
                "total_score": int(item["total_score"]),
                "grade": item["grade"],
                "scanned_at": item["scanned_at"],
                "dimensions": {},
            }
        )
        if len(history) >= limit:
            break
    return history


def _attach_result_ids(items: list[dict], json_records: list[dict]) -> None:
    records_by_url: dict[str, list[dict]] = {}
    for record in json_records:
        records_by_url.setdefault(record["url"], []).append(record)

    used_result_ids: set[str] = set()
    max_match_delta_seconds = 300

    for item in items:
        item["result_id"] = item.get("result_id", "") or ""
        candidates = records_by_url.get(str(item.get("url", "")), [])
        if not candidates:
            continue

        target_dt = _parse_timestamp(str(item.get("scanned_at", "")))
        chosen: dict | None = None
        chosen_delta: float | None = None

        for record in candidates:
            result_id = str(record["result_id"])
            if result_id in used_result_ids:
                continue

            record_dt = record.get("_parsed_dt")
            if target_dt is not None and isinstance(record_dt, datetime):
                delta = abs((record_dt - target_dt).total_seconds())
                if chosen is None or chosen_delta is None or delta < chosen_delta:
                    chosen = record
                    chosen_delta = delta
            elif chosen is None:
                chosen = record

        if chosen is None:
            continue

        if chosen_delta is not None and chosen_delta > max_match_delta_seconds:
            continue

        item["result_id"] = str(chosen["result_id"])
        used_result_ids.add(item["result_id"])


def _load_history_items_from_json(*, limit: int = 20) -> list[dict]:
    items = []
    for record in _load_json_result_records()[:limit]:
        score = record["total_score"]
        if score is None:
            continue
        trend_history = _get_json_url_history(record["url"], limit=5)
        items.append(
            {
                "scan_id": record["result_id"],
                "result_id": record["result_id"],
                "url": record["url"],
                "total_score": int(score),
                "grade": record["grade"],
                "scanned_at": record["scanned_at"],
                "trend_history": trend_history,
            }
        )
    return items


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
        draft_mode = is_ghost_url(url)
        fetch_result = fetch_html(url)
        analysis_url = fetch_result.final_url or url
        result = parse_content(fetch_result.html, analysis_url)
        result["geo"] = check_geo(
            result, fetch_result.html, analysis_url,
            draft_mode=draft_mode, fetch_result=fetch_result,
        )
        result["draft_mode"] = draft_mode
        result["analysis_id"] = result_id
        result["created_at"] = datetime.now(UTC).isoformat()
        (RESULTS_DIR / f"{result_id}.json").write_text(
            json.dumps(result, ensure_ascii=True, indent=2)
        )

        conn = get_conn()
        try:
            init_db(conn)
            url_id = upsert_url(conn, analysis_url)
            save_scan(conn, url_id, result)
        finally:
            conn.close()

        return RedirectResponse(url=f"/results/{result_id}", status_code=303)
    except Exception as e:
        # Return error page instead of 500
        from src.fetcher.ghost_fetcher import GhostAPIError
        error_message = str(e)
        if isinstance(e, GhostAPIError):
            error_message = f"Ghost API: {error_message}"
        elif "SSL" in error_message or "certificate" in error_message.lower():
            error_message = (
                f"SSL certificate error for {url}. "
                "The target site may have an invalid certificate."
            )
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

    # Generate Action Toolkit
    geo = result.get("geo", {})
    toolkit = {}
    fix_snippets = []
    if geo:
        toolkit["checklist"] = generate_checklist(geo)
        toolkit["robots_txt"] = generate_robots_txt(
            geo, url=result.get("url", ""),
        )
        schemas = generate_all_schemas(result)
        toolkit["schema_json"] = schemas_to_html(schemas)
        fix_snippets = generate_fixes(geo, result, url=result.get("url", ""))

    trend_data = []
    analyzed_url = result.get("url", "")
    if analyzed_url:
        conn = get_conn()
        try:
            init_db(conn)
            trend_data = get_url_history(conn, analyzed_url, limit=10)
        finally:
            conn.close()
        if not trend_data:
            trend_data = _get_json_url_history(analyzed_url, limit=10)

    return TEMPLATES.TemplateResponse(
        "results.html",
        {
            "request": request,
            "result": result,
            "result_id": result_id,
            "excerpts": excerpts,
            "toolkit": toolkit,
            "fix_snippets": fix_snippets,
            "trend_data": trend_data,
            "t": get_translations(request),
        },
    )


@router.get("/results/{result_id}/card.png")
def score_card_image(result_id: str) -> Response:
    """Generate and serve GEO Score Card as PNG image."""
    path = _get_safe_result_path(result_id)
    if path is None or not path.exists():
        return Response(status_code=404, content="Not found")

    # Check for cached card image
    card_path = RESULTS_DIR / f"{result_id}_card.png"
    if not card_path.exists():
        result = json.loads(path.read_text())
        try:
            generate_card_image_sync(result, str(card_path))
        except Exception:
            # Playwright not available — return a fallback
            return Response(
                status_code=503,
                content="Card generation unavailable",
            )

    return Response(
        content=card_path.read_bytes(),
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.get("/results/{result_id}/badge.svg")
def badge_svg(result_id: str) -> Response:
    """Serve dynamic SVG badge for a stored result."""
    path = _get_safe_result_path(result_id)
    if path is None or not path.exists():
        # Return a "no data" badge
        svg = generate_badge_svg(0, "?", label="GEO Score")
        return Response(
            content=svg, media_type="image/svg+xml",
        )

    result = json.loads(path.read_text())
    geo = result.get("geo", {})
    score_data = geo.get("geo_score", {})

    svg = generate_badge_svg(
        score=score_data.get("total", 0),
        grade=score_data.get("grade", "?"),
    )
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/history")
def history(request: Request) -> object:
    history_items: list[dict] = []
    history_source = "sqlite"
    json_records = _load_json_result_records()

    conn = get_conn()
    try:
        init_db(conn)
        rows = conn.execute(
            """
            SELECT s.id AS scan_id, u.url, s.total_score, s.grade, s.scanned_at
            FROM scans s JOIN urls u ON u.id = s.url_id
            ORDER BY s.scanned_at DESC, s.id DESC LIMIT 20
            """
        ).fetchall()
        history_items = [dict(row) for row in rows]
        for item in history_items:
            item["trend_history"] = get_url_history(conn, item["url"], limit=5)
    finally:
        conn.close()

    if history_items:
        _attach_result_ids(history_items, json_records)
    else:
        history_source = "json"
        history_items = _load_history_items_from_json(limit=20)

    return TEMPLATES.TemplateResponse(
        "history.html",
        {
            "request": request,
            "items": history_items,
            "history_source": history_source,
            "t": get_translations(request),
        },
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
    content = """# GEO Checker — AI-optimized robots.txt
# https://gc.ranran.tw

# AI Search Crawlers
User-agent: GPTBot
Allow: /

User-agent: OAI-SearchBot
Allow: /

User-agent: ClaudeBot
Allow: /

User-agent: anthropic-ai
Allow: /

User-agent: PerplexityBot
Allow: /

User-agent: Google-Extended
Allow: /

User-agent: Applebot-Extended
Allow: /

User-agent: Meta-ExternalAgent
Allow: /

User-agent: Amazonbot
Allow: /

User-agent: YouBot
Allow: /

User-agent: CCBot
Allow: /

User-agent: PhindBot
Allow: /

User-agent: cohere-ai
Allow: /

User-agent: Bytespider
Allow: /

User-agent: *
Allow: /

Sitemap: https://gc.ranran.tw/sitemap.xml
"""
    return Response(content=content, media_type="text/plain")


@router.get("/llms.txt")
def llms_txt() -> Response:
    content = """# GEO Checker — AI Content Index
# https://gc.ranran.tw

> GEO Checker is a free, open-source tool that analyzes
> web pages for Generative Engine Optimization (GEO).
> It checks whether AI search engines (ChatGPT, Claude,
> Perplexity, Gemini) can find, understand, and cite
> your content.

## Key Pages

- [Home](https://gc.ranran.tw/): Analyze any URL for GEO
- [Compare](https://gc.ranran.tw/compare): Side-by-side comparison
- [History](https://gc.ranran.tw/history): Past analysis results
- [API Docs](https://gc.ranran.tw/api/docs): REST API documentation

## Features

- 14 AI crawler monitoring (GPTBot, ClaudeBot, etc.)
- E-E-A-T author authority signals
- Content freshness detection
- llms.txt standard detection
- AI Citation Simulator
- Action Toolkit (robots.txt, Schema, Checklist)
- GEO Score Card for social sharing
- AI-Ready Badge for website embedding

## API

- POST /api/v1/analyze — Submit URL for analysis
- GET /api/v1/jobs/{id} — Get analysis result
- POST /api/v1/compare — Compare 2-3 URLs
- GET /api/v1/health — Health check

## Contact

- Website: https://ai.chiba.tw
- Built by Maki Chiang
"""
    return Response(content=content, media_type="text/plain")


@router.get("/sitemap.xml")
def sitemap_xml() -> Response:
    content = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://gc.ranran.tw/</loc>
    <lastmod>2026-03-27</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>https://gc.ranran.tw/compare</loc>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>
  <url>
    <loc>https://gc.ranran.tw/history</loc>
    <changefreq>daily</changefreq>
    <priority>0.6</priority>
  </url>
  <url>
    <loc>https://gc.ranran.tw/api/docs</loc>
    <changefreq>monthly</changefreq>
    <priority>0.5</priority>
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
            draft_mode = is_ghost_url(item["url"])
            fetch_result = fetch_html(item["url"])
            analysis_url = fetch_result.final_url or item["url"]
            parsed = parse_content(fetch_result.html, analysis_url)
            geo = check_geo(
                parsed, fetch_result.html, analysis_url,
                draft_mode=draft_mode, fetch_result=fetch_result,
            )
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
