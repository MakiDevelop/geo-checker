"""HTML fetching utilities with SSRF protection.

All outbound HTTP in this module routes through `pinned_fetch` from
`src.security.url_guard`, which performs SSRF validation, pins the resolved
IP, and connects directly to that IP with TLS SNI/Host header set to the
original hostname. DNS rebinding between validate-time and connect-time is
therefore impossible — the server cannot swap IPs under us.

The Playwright JS render path (`render_js_content`) is also protected: it
resolves + pins via `url_guard.resolve_webhook_target` before launching
Chromium and passes the pinned IP into Chromium via `--host-resolver-rules`.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from urllib.parse import urlparse

from cachetools import TTLCache
from urllib3.exceptions import HTTPError as Urllib3HTTPError

from src.fetcher.js_render_fetcher import render_js_content
from src.security.url_guard import (
    PinnedFetchResult,
    UnsafeWebhookTarget,
    WebhookValidationError,
    pinned_fetch,
)

# Security limits
MAX_RESPONSE_SIZE = 10 * 1024 * 1024  # 10 MB max response size
_LLMS_TXT_MAX_SIZE = 100_000  # 100KB limit for llms.txt
_ROBOTS_TXT_MAX_SIZE = 512 * 1024  # 512KB limit for robots.txt
_USER_AGENT = "GEO-Checker/4.0 (+https://gc.ranran.tw)"

# Domain-level cache for robots.txt and llms.txt (TTL 10 min, max 100 domains)
# Protected by lock for thread safety (ThreadPoolExecutor in job_queue)
_cache_lock = threading.Lock()
_robots_cache: TTLCache[str, tuple[bool, str]] = TTLCache(maxsize=100, ttl=600)
_llms_cache: TTLCache[str, tuple[bool, str, str]] = TTLCache(maxsize=100, ttl=600)

_CHARSET_PATTERN = re.compile(r"charset\s*=\s*([\w\-]+)", re.IGNORECASE)


@dataclass
class FetchResult:
    """Result of fetching a URL, carrying HTML + metadata for downstream use."""

    html: str
    headers: dict[str, str] = field(default_factory=dict)
    final_url: str = ""
    robots_txt: str = ""
    robots_txt_found: bool = False
    is_ghost: bool = False
    llms_txt: str = ""
    llms_txt_found: bool = False
    llms_txt_path: str = ""  # which variant was found


def _is_url(source: str) -> bool:
    parsed = urlparse(source)
    return parsed.scheme in {"http", "https"}


def _extract_charset(content_type: str) -> str | None:
    if not content_type:
        return None
    match = _CHARSET_PATTERN.search(content_type)
    return match.group(1) if match else None


def _decode_body(body: bytes, content_type: str) -> str:
    encoding = _extract_charset(content_type) or "utf-8"
    try:
        return body.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        return body.decode("utf-8", errors="replace")


def _safe_pinned_fetch(
    url: str,
    *,
    timeout_seconds: float,
    max_size: int,
    max_redirects: int,
) -> PinnedFetchResult | None:
    """Run `pinned_fetch` and swallow expected failure modes by returning None.

    Used by the optional probes (robots.txt / llms.txt). The main HTML path
    deliberately does NOT swallow — see `fetch_html` for the loud failures.
    """
    try:
        return pinned_fetch(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout_seconds=timeout_seconds,
            max_size=max_size,
            max_redirects=max_redirects,
        )
    except (
        WebhookValidationError,
        UnsafeWebhookTarget,
        Urllib3HTTPError,
        OSError,
        ValueError,
    ):
        return None


def _fetch_robots_txt(url: str) -> tuple[bool, str]:
    """Fetch robots.txt for the given URL's domain.

    Uses domain-level TTL cache (10 min) and the SSRF-safe pinned fetcher.
    """
    parsed = urlparse(url)
    cache_key = f"{parsed.scheme}://{parsed.netloc}"
    with _cache_lock:
        if cache_key in _robots_cache:
            return _robots_cache[cache_key]

    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    result: tuple[bool, str] = (False, "")
    fetched = _safe_pinned_fetch(
        robots_url,
        timeout_seconds=10,
        max_size=_ROBOTS_TXT_MAX_SIZE,
        max_redirects=0,
    )
    if fetched is not None and fetched.status == 200:
        result = (True, _decode_body(fetched.body, fetched.headers.get("Content-Type", "")))

    with _cache_lock:
        _robots_cache[cache_key] = result
    return result


def _fetch_llms_txt(url: str) -> tuple[bool, str, str]:
    """Probe for llms.txt variants at the root of the domain.

    Uses domain-level TTL cache (10 min) and the SSRF-safe pinned fetcher.
    Short timeout (3s each) and size-limited to avoid latency DoS.
    Returns (found, content, path_found).
    """
    parsed = urlparse(url)
    cache_key = f"{parsed.scheme}://{parsed.netloc}"
    with _cache_lock:
        if cache_key in _llms_cache:
            return _llms_cache[cache_key]

    base = f"{parsed.scheme}://{parsed.netloc}"
    variants = ["/llms.txt", "/llm.txt", "/llms-full.txt"]
    for path in variants:
        probe_url = f"{base}{path}"
        fetched = _safe_pinned_fetch(
            probe_url,
            timeout_seconds=3,
            max_size=_LLMS_TXT_MAX_SIZE,
            max_redirects=0,
        )
        if fetched is None or fetched.status != 200:
            continue
        content_type = fetched.headers.get("Content-Type", "")
        if content_type and not ("text/" in content_type or "markdown" in content_type):
            continue
        content = _decode_body(fetched.body, content_type)
        found = (True, content[:10000], path)
        with _cache_lock:
            _llms_cache[cache_key] = found
        return found

    miss = (False, "", "")
    with _cache_lock:
        _llms_cache[cache_key] = miss
    return miss


def _needs_js_render(html: str, content_type: str) -> bool:
    if "JavaScript must be enabled" in html:
        return True
    if content_type and "text/html" not in content_type:
        return True
    if len(html) < 2000 and "<p" not in html and "<h1" not in html:
        return True
    return False


def fetch_html(source: str) -> FetchResult:
    """Fetch raw HTML for analysis with end-to-end SSRF protection.

    Security model:
    - Only http/https URLs accepted (no local file paths)
    - Resolution + IP pinning + TLS SNI handled by `pinned_fetch`; DNS
      rebinding cannot succeed because the connect target is the IP captured
      at validate time, not whatever DNS returns at request time.
    - Each redirect re-runs the same validation against the new URL.
    - Response size capped at MAX_RESPONSE_SIZE; aborts before consuming
      arbitrary memory.
    """
    # Ghost Admin API: bypass normal fetch for configured Ghost URLs
    from src.fetcher.ghost_fetcher import fetch_ghost_post, is_ghost_url
    if is_ghost_url(source):
        html = fetch_ghost_post(source)
        return FetchResult(html=html, final_url=source, is_ghost=True)

    # Security: Only accept URLs, never local file paths
    if not _is_url(source):
        raise ValueError("Only http and https URLs are allowed")

    try:
        fetched = pinned_fetch(
            source,
            headers={"User-Agent": _USER_AGENT},
            timeout_seconds=15,
            max_size=MAX_RESPONSE_SIZE,
            max_redirects=5,
        )
    except (WebhookValidationError, UnsafeWebhookTarget) as exc:
        raise ValueError(f"SSRF protection: {exc}") from exc
    except Urllib3HTTPError as exc:
        raise RuntimeError(f"Network error fetching {source}: {exc}") from exc

    if fetched.status >= 400:
        raise RuntimeError(
            f"HTTP {fetched.status} when fetching {fetched.final_url}"
        )

    content_type = fetched.headers.get("Content-Type", "")
    html = _decode_body(fetched.body, content_type)

    if _needs_js_render(html, content_type):
        try:
            html = render_js_content(fetched.final_url)
        except (WebhookValidationError, UnsafeWebhookTarget) as exc:
            raise ValueError(f"SSRF protection (js render): {exc}") from exc
        except RuntimeError as exc:
            raise RuntimeError("Unable to render JS page within timeout") from exc

    # Fetch robots.txt and llms.txt in the same pipeline (also via pinned_fetch)
    robots_found, robots_text = _fetch_robots_txt(fetched.final_url)
    llms_found, llms_text, llms_path = _fetch_llms_txt(fetched.final_url)

    return FetchResult(
        html=html,
        headers=fetched.headers,
        final_url=fetched.final_url,
        robots_txt=robots_text,
        robots_txt_found=robots_found,
        llms_txt=llms_text,
        llms_txt_found=llms_found,
        llms_txt_path=llms_path,
    )
