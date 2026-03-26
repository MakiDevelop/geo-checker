"""HTML fetching utilities with SSRF protection."""
from __future__ import annotations

import socket
from dataclasses import dataclass, field
from ipaddress import ip_address
from urllib.parse import urljoin, urlparse

import requests

from src.fetcher.js_render_fetcher import render_js_content

# Security limits
MAX_RESPONSE_SIZE = 10 * 1024 * 1024  # 10 MB max response size


@dataclass
class FetchResult:
    """Result of fetching a URL, carrying HTML + metadata for downstream use."""

    html: str
    headers: dict[str, str] = field(default_factory=dict)
    final_url: str = ""
    robots_txt: str = ""
    robots_txt_found: bool = False
    is_ghost: bool = False


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

    Uses allow_redirects=False to prevent SSRF via redirect from robots.txt.
    """
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        # Validate robots.txt URL (same domain, should be safe)
        _, _, error = _resolve_and_validate_url(robots_url)
        if error:
            return False, ""
        response = requests.get(robots_url, timeout=10, allow_redirects=False)
        # Only accept direct 200 responses — redirected robots.txt is uncommon
        # and could be an SSRF vector
        if response.status_code != 200:
            return False, ""
        return True, response.text
    except requests.RequestException:
        return False, ""


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

    # Fetch robots.txt in the same pipeline (avoids separate unprotected request later)
    robots_found, robots_text = _fetch_robots_txt(current_url)

    return FetchResult(
        html=html,
        headers=resp_headers,
        final_url=current_url,
        robots_txt=robots_text,
        robots_txt_found=robots_found,
    )
