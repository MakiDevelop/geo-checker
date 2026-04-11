"""JS-rendered HTML fetcher using Playwright with SSRF protection."""
from __future__ import annotations

import ipaddress
import sys
import threading
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from src.security.url_guard import (
    UnsafeWebhookTarget,
    resolve_webhook_target,
)

if TYPE_CHECKING:
    from playwright.sync_api import Request, Route
else:
    Request = Any
    Route = Any

# Concurrency control: limit simultaneous browser instances.
# Keep low to prevent OOM on limited memory servers (2GB RAM).
MAX_CONCURRENT_BROWSERS = 1
_browser_semaphore = threading.Semaphore(MAX_CONCURRENT_BROWSERS)

# Denylist for IP-literal second-layer check.
# Must stay in sync with src/security/url_guard.py _DENYLIST_IPV4/IPV6.
_PRIVATE_NETS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("ff00::/8"),
)


def _is_private_ip_literal(host: str) -> bool:
    """Return True if `host` is an IP literal in a private/reserved range."""
    if not host:
        return False
    # Strip IPv6 brackets
    bare = host.strip("[]")
    try:
        addr = ipaddress.ip_address(bare)
    except ValueError:
        return False  # hostname, not IP literal; host-resolver-rules handles it
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        return True  # IPv4-mapped IPv6 is always blocked (matches url_guard)
    return any(addr in net for net in _PRIVATE_NETS)


def _is_rendered_html(html: str) -> bool:
    if "JavaScript must be enabled" in html:
        return 'data-geo-extracted="true"' in html
    return True


def _render_once(
    url: str,
    pinned_ip: str,
    hostname: str,
    timeout_ms: int,
    block_assets: bool,
) -> str:
    """Launch a hardened Chromium and render `url`.

    Security invariants:
    - Chromium DNS is pinned: `hostname` -> `pinned_ip`, all others NOTFOUND.
    - WebRTC / DoH / Service Workers disabled (they bypass host-resolver-rules).
    - IP-literal requests to private ranges aborted at page.route() level.
    - Post-goto `page.url` validated against private IP ranges.
    """
    allowed_resource_types = {"document", "script", "xhr", "fetch"}
    selectors = [
        "main",
        '[role="main"]',
        ".notion-page-content",
        'div[data-content-editable-leaf="true"]',
    ]
    goto_timeout = min(timeout_ms, 20000)

    chromium_args = [
        # Layer 1: DNS pinning. No extra quotes around the value.
        f"--host-resolver-rules=MAP {hostname} {pinned_ip}, MAP * ~NOTFOUND",
        # DoH bypasses --host-resolver-rules; explicitly off.
        "--disable-features=DnsOverHttps",
        # WebRTC STUN uses its own resolver; force it to proxy-only UDP.
        "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
        # Suppress background pings that would error loudly under MAP * ~NOTFOUND.
        "--disable-background-networking",
        "--disable-client-side-phishing-detection",
        "--no-default-browser-check",
        "--no-first-run",
        "--disable-sync",
        "--disable-translate",
    ]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=chromium_args,
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            service_workers="block",
        )
        page = context.new_page()

        def _route_handler(route: Route, request: Request) -> None:
            req_url = request.url
            try:
                parsed = urlparse(req_url)
            except Exception:
                route.abort("blockedbyclient")
                return

            # Layer 2: block direct IP-literal access to private ranges.
            host_field = parsed.hostname or ""
            if _is_private_ip_literal(host_field):
                print(
                    f"[ssrf-guard] playwright blocked IP-literal request: {req_url}",
                    file=sys.stderr,
                )
                route.abort("blockedbyclient")
                return

            if block_assets:
                if request.resource_type in allowed_resource_types:
                    route.continue_()
                else:
                    route.abort("blockedbyclient")
            else:
                route.continue_()

        page.route("**/*", _route_handler)

        try:
            # Use domcontentloaded; networkidle can be gamed into DoS.
            page.goto(url, wait_until="domcontentloaded", timeout=goto_timeout)
        except PlaywrightTimeoutError:
            pass  # partial render acceptable

        # Post-goto validation: catch JS-driven redirects to private IPs.
        final_url = page.url
        try:
            final_parsed = urlparse(final_url)
        except Exception:
            final_parsed = None
        if final_parsed is not None and _is_private_ip_literal(
            final_parsed.hostname or ""
        ):
            context.close()
            browser.close()
            raise UnsafeWebhookTarget(
                f"playwright post-goto URL resolved to private IP: {final_url}"
            )

        for selector in selectors:
            try:
                page.wait_for_selector(selector, timeout=5000)
                break
            except PlaywrightTimeoutError:
                continue

        page.evaluate(
            """() => {
                const leafs = Array.from(
                    document.querySelectorAll('div[data-content-editable-leaf="true"]')
                );
                if (!leafs.length) {
                    return;
                }
                const texts = leafs
                    .map((node) => (node.innerText || "").trim())
                    .filter((text) => text);
                if (!texts.length) {
                    return;
                }
                const main = document.createElement("main");
                main.setAttribute("data-geo-extracted", "true");
                for (const text of texts) {
                    const paragraph = document.createElement("p");
                    paragraph.textContent = text;
                    main.appendChild(paragraph);
                }
                document.body.prepend(main);
            }"""
        )

        html = page.content()
        context.close()
        browser.close()
        return html


def render_js_content(url: str, timeout_ms: int = 30000) -> str:
    """Render a JS-driven page with SSRF-hardened Chromium and return HTML.

    Before launching Chromium, resolve and validate the target via
    `resolve_webhook_target` (allowlist disabled - user-supplied URL is
    never trusted). The resulting `pinned_ip` + `hostname` are then passed
    to Chromium as `--host-resolver-rules`, closing Chromium's DNS rebinding
    window in the same way Python's `pinned_fetch` closes urllib3's.

    Raises:
        UnsafeWebhookTarget / WebhookValidationError: URL rejected by
            `url_guard` or post-goto validation.
        RuntimeError: render timeout or rendered HTML still looks unrendered.
    """
    # Validate + pin. respect_allowlist=False because user URLs are untrusted.
    target = resolve_webhook_target(url, respect_allowlist=False)

    acquired = _browser_semaphore.acquire(timeout=60)
    if not acquired:
        raise RuntimeError(
            "Too many concurrent rendering requests. Please try again later."
        )

    try:
        try:
            html = _render_once(
                url,
                pinned_ip=target.pinned_ip,
                hostname=target.hostname,
                timeout_ms=timeout_ms,
                block_assets=True,
            )
            if _is_rendered_html(html):
                return html
            html = _render_once(
                url,
                pinned_ip=target.pinned_ip,
                hostname=target.hostname,
                timeout_ms=timeout_ms + 5000,
                block_assets=False,
            )
            if _is_rendered_html(html):
                return html
        except PlaywrightTimeoutError as exc:
            raise RuntimeError("Unable to render JS page within timeout") from exc
        raise RuntimeError("Unable to render JS page within timeout")
    finally:
        _browser_semaphore.release()
