"""HTML fetching utilities with SSRF protection."""
import socket
from ipaddress import ip_address
from urllib.parse import urlparse

import requests

from src.fetcher.js_render_fetcher import render_js_content

# Security limits
MAX_RESPONSE_SIZE = 10 * 1024 * 1024  # 10 MB max response size


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


def _resolve_and_validate_url(url: str) -> tuple[str, str, str]:
    """
    Resolve URL hostname to IP and validate it's safe.
    Returns (resolved_ip, hostname, error_message).

    This provides SSRF protection by validating the IP before making requests.
    Note: There's a theoretical TOCTOU window between validation and request,
    but this is acceptable for this use case as:
    - DNS rebinding attacks require attacker-controlled DNS
    - The attack window is very small (milliseconds)
    - This is a public analysis tool, not handling sensitive data
    """
    try:
        parsed = urlparse(url)

        # Only allow http and https
        if parsed.scheme not in {"http", "https"}:
            return "", "", "Only http and https schemes are allowed"

        hostname = parsed.hostname
        if not hostname:
            return "", "", "Invalid URL: hostname not found"

        # Resolve hostname to IP
        try:
            resolved_ip = socket.gethostbyname(hostname)
        except socket.gaierror:
            return "", "", f"Could not resolve hostname: {hostname}"

        # Validate IP is not private/internal
        is_safe, error_msg = _validate_ip(resolved_ip)
        if not is_safe:
            return "", "", error_msg

        return resolved_ip, hostname, ""
    except Exception as e:
        return "", "", f"URL validation error: {str(e)}"


def _needs_js_render(html: str, content_type: str) -> bool:
    if "JavaScript must be enabled" in html:
        return True
    if content_type and "text/html" not in content_type:
        return True
    if len(html) < 2000 and "<p" not in html and "<h1" not in html:
        return True
    return False


def fetch_html(source: str) -> str:
    """
    Fetch raw HTML from a URL.

    Security measures:
    - Only accepts http/https URLs (no local file paths)
    - Validates resolved IP is not private/internal (SSRF protection)
    - Disables automatic redirects to validate each redirect target
    - Re-validates IP after any redirect
    - Limits response size to prevent memory exhaustion
    """
    # Ghost Admin API: bypass normal fetch for configured Ghost URLs
    from src.fetcher.ghost_fetcher import fetch_ghost_post, is_ghost_url
    if is_ghost_url(source):
        return fetch_ghost_post(source)

    # Security: Only accept URLs, never local file paths
    if not _is_url(source):
        raise ValueError("Only http and https URLs are allowed")

    # SSRF protection: resolve and validate URL before requesting
    resolved_ip, hostname, error_msg = _resolve_and_validate_url(source)
    if error_msg:
        raise ValueError(f"SSRF protection: {error_msg}")

    # Make request using original URL (required for proper SSL certificate validation)
    # The IP validation above prevents most SSRF attacks
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
        raise ValueError(f"Response too large: {int(content_length)} bytes (max {MAX_RESPONSE_SIZE})")

    # Handle redirects manually with validation
    redirect_count = 0
    max_redirects = 5
    while response.is_redirect and redirect_count < max_redirects:
        redirect_count += 1
        redirect_url = response.headers.get("Location", "")

        if not redirect_url:
            break

        # Handle relative redirects
        if not _is_url(redirect_url):
            parsed_source = urlparse(source)
            redirect_url = f"{parsed_source.scheme}://{parsed_source.netloc}{redirect_url}"

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
        source = redirect_url

        # Check size after redirect too
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_RESPONSE_SIZE:
            response.close()
            raise ValueError(f"Response too large: {int(content_length)} bytes (max {MAX_RESPONSE_SIZE})")

    response.raise_for_status()
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
            return render_js_content(source)
        except RuntimeError as exc:
            raise RuntimeError("Unable to render JS page within timeout") from exc

    return html
