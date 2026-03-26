"""HTML fetching utilities with SSRF protection."""
from __future__ import annotations

import socket
import threading
from dataclasses import dataclass, field
from ipaddress import ip_address
from urllib.parse import urljoin, urlparse

import requests
from cachetools import TTLCache

from src.fetcher.js_render_fetcher import render_js_content

# Security limits
MAX_RESPONSE_SIZE = 10 * 1024 * 1024  # 10 MB max response size

# Domain-level cache for robots.txt and llms.txt (TTL 10 min, max 100 domains)
# Protected by lock for thread safety (ThreadPoolExecutor in job_queue)
_cache_lock = threading.Lock()
_robots_cache: TTLCache[str, tuple[bool, str]] = TTLCache(maxsize=100, ttl=600)
_llms_cache: TTLCache[str, tuple[bool, str, str]] = TTLCache(maxsize=100, ttl=600)


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


def _validate_ip(ip_str: str) -> tuple[bool, str]:
    """Check if an IP address is safe (not private/internal)."""
    try:
        ip = ip_address(ip_str)
        if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
            return False, f"Access to private/internal IP addresses is forbidden: {ip_str}"
        return True, ""
    except ValueError:
        return False, f"Invalid IP address: {ip_str}"


def _resolve_and_validate_url(url: str) -> tuple[list[str], str, str]:
    """
    Resolve URL hostname to IPs and validate ALL are safe.
    Returns (resolved_ips, hostname, error_message).

    Uses getaddrinfo() to check both IPv4 and IPv6 addresses.
    """
    try:
        parsed = urlparse(url)

        # Only allow http and https
        if parsed.scheme not in {"http", "https"}:
            return [], "", "Only http and https schemes are allowed"

        hostname = parsed.hostname
        if not hostname:
            return [], "", "Invalid URL: hostname not found"

        # Resolve hostname to ALL IPs (IPv4 + IPv6)
        try:
            addrinfos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        except socket.gaierror:
            return [], "", f"Could not resolve hostname: {hostname}"

        if not addrinfos:
            return [], "", f"Could not resolve hostname: {hostname}"

        # Validate EVERY resolved IP
        resolved_ips = []
        seen: set[str] = set()
        for _family, _type, _proto, _canonname, sockaddr in addrinfos:
            ip_str: str = sockaddr[0]
            if ip_str in seen:
                continue
            seen.add(ip_str)

            is_safe, error_msg = _validate_ip(ip_str)
            if not is_safe:
                return [], "", error_msg
            resolved_ips.append(ip_str)

        return resolved_ips, hostname, ""
    except Exception as e:
        return [], "", f"URL validation error: {str(e)}"


def _fetch_robots_txt(url: str) -> tuple[bool, str]:
    """Fetch robots.txt for the given URL's domain.

    Uses domain-level TTL cache (10 min) to avoid repeated fetches.
    Uses allow_redirects=False to prevent SSRF via redirect.
    """
    parsed = urlparse(url)
    cache_key = f"{parsed.scheme}://{parsed.netloc}"
    with _cache_lock:
        if cache_key in _robots_cache:
            return _robots_cache[cache_key]

    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        _, _, error = _resolve_and_validate_url(robots_url)
        if error:
            result = (False, "")
        else:
            response = requests.get(
                robots_url, timeout=10, allow_redirects=False,
            )
            if response.status_code != 200:
                result = (False, "")
            else:
                result = (True, response.text)
    except requests.RequestException:
        result = (False, "")

    with _cache_lock:
        _robots_cache[cache_key] = result
    return result


_LLMS_TXT_MAX_SIZE = 100_000  # 100KB limit for llms.txt


def _fetch_llms_txt(url: str) -> tuple[bool, str, str]:
    """Probe for llms.txt variants at the root of the domain.

    Uses domain-level TTL cache (10 min).
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
        try:
            _, _, error = _resolve_and_validate_url(probe_url)
            if error:
                continue
            resp = requests.get(
                probe_url, timeout=3,
                allow_redirects=False, stream=True,
            )
            if resp.status_code != 200:
                resp.close()
                continue
            ct = resp.headers.get("Content-Type", "")
            if not ("text/" in ct or "markdown" in ct or not ct):
                resp.close()
                continue
            # Size-limited read
            cl = resp.headers.get("Content-Length", "")
            if cl and int(cl) > _LLMS_TXT_MAX_SIZE:
                resp.close()
                continue
            chunks = []
            total = 0
            for chunk in resp.iter_content(4096):
                total += len(chunk)
                if total > _LLMS_TXT_MAX_SIZE:
                    resp.close()
                    break
                chunks.append(chunk)
            else:
                content = b"".join(chunks).decode(
                    "utf-8", errors="replace",
                )
                found = (True, content[:10000], path)
                with _cache_lock:
                    _llms_cache[cache_key] = found
                return found
        except (requests.RequestException, ValueError):
            continue
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
    """
    Fetch raw HTML from a URL and return a FetchResult with all metadata.

    Security measures:
    - Only accepts http/https URLs (no local file paths)
    - Validates ALL resolved IPs (IPv4+IPv6) are not private/internal (SSRF protection)
    - Disables automatic redirects to validate each redirect target
    - Re-validates IP after any redirect using urljoin for normalization
    - Limits response size to prevent memory exhaustion
    - Fetches robots.txt in the same pipeline to avoid redundant requests
    """
    # Ghost Admin API: bypass normal fetch for configured Ghost URLs
    from src.fetcher.ghost_fetcher import fetch_ghost_post, is_ghost_url
    if is_ghost_url(source):
        html = fetch_ghost_post(source)
        return FetchResult(html=html, final_url=source, is_ghost=True)

    # Security: Only accept URLs, never local file paths
    if not _is_url(source):
        raise ValueError("Only http and https URLs are allowed")

    # SSRF protection: resolve and validate URL before requesting
    resolved_ips, hostname, error_msg = _resolve_and_validate_url(source)
    if error_msg:
        raise ValueError(f"SSRF protection: {error_msg}")

    # Make request using original URL (required for proper SSL certificate validation)
    response = requests.get(
        source,
        timeout=15,
        allow_redirects=False,  # Disable automatic redirects for security
        stream=True,  # Enable streaming for size check
    )

    # Check Content-Length header first (if available)
    content_length = response.headers.get("Content-Length")
    if content_length and int(content_length) > MAX_RESPONSE_SIZE:
        response.close()
        raise ValueError(
            f"Response too large: {int(content_length)} bytes "
            f"(max {MAX_RESPONSE_SIZE})"
        )

    # Track final URL for robots.txt domain
    current_url = source

    # Handle redirects manually with validation
    redirect_count = 0
    max_redirects = 5
    while response.is_redirect and redirect_count < max_redirects:
        redirect_count += 1
        location = response.headers.get("Location", "")

        if not location:
            break

        # Normalize redirect URL using urljoin (handles relative paths correctly)
        redirect_url = urljoin(current_url, location)

        # Validate redirect URL (prevents redirect to internal IPs)
        _, _, redirect_error = _resolve_and_validate_url(redirect_url)
        if redirect_error:
            raise ValueError(f"SSRF protection: Redirect blocked - {redirect_error}")

        response = requests.get(
            redirect_url,
            timeout=15,
            allow_redirects=False,
            stream=True,
        )
        current_url = redirect_url

        # Check size after redirect too
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_RESPONSE_SIZE:
            response.close()
            raise ValueError(
                f"Response too large: {int(content_length)} bytes "
                f"(max {MAX_RESPONSE_SIZE})"
            )

    response.raise_for_status()

    # Capture response headers for downstream use (X-Robots-Tag etc.)
    resp_headers = dict(response.headers)
    content_type = response.headers.get("Content-Type", "")

    # Read content with size limit (for cases without Content-Length header)
    chunks = []
    total_size = 0
    for chunk in response.iter_content(chunk_size=8192, decode_unicode=False):
        total_size += len(chunk)
        if total_size > MAX_RESPONSE_SIZE:
            response.close()
            raise ValueError(f"Response too large: exceeded {MAX_RESPONSE_SIZE} bytes")
        chunks.append(chunk)

    # Decode content
    content_bytes = b"".join(chunks)
    encoding = response.encoding or "utf-8"
    try:
        html = content_bytes.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        html = content_bytes.decode("utf-8", errors="replace")

    if _needs_js_render(html, content_type):
        try:
            html = render_js_content(current_url)
        except RuntimeError as exc:
            raise RuntimeError("Unable to render JS page within timeout") from exc

    # Fetch robots.txt and llms.txt in the same pipeline
    robots_found, robots_text = _fetch_robots_txt(current_url)
    llms_found, llms_text, llms_path = _fetch_llms_txt(current_url)

    return FetchResult(
        html=html,
        headers=resp_headers,
        final_url=current_url,
        robots_txt=robots_text,
        robots_txt_found=robots_found,
        llms_txt=llms_text,
        llms_txt_found=llms_found,
        llms_txt_path=llms_path,
    )
