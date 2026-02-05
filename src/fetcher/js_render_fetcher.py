"""JS-rendered HTML fetcher using Playwright with concurrency control."""
import threading

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

# Concurrency control: limit simultaneous browser instances
# Keep low to prevent OOM on limited memory servers (2GB RAM)
# With 2 uvicorn workers, max total browsers = 2 workers x 1 = 2 instances
MAX_CONCURRENT_BROWSERS = 1
_browser_semaphore = threading.Semaphore(MAX_CONCURRENT_BROWSERS)


def _is_rendered_html(html: str) -> bool:
    if "JavaScript must be enabled" in html:
        return 'data-geo-extracted="true"' in html
    return True


def _render_once(url: str, timeout_ms: int, block_assets: bool) -> str:
    allowed_types = {"document", "script", "xhr", "fetch"}
    selectors = [
        "main",
        '[role="main"]',
        ".notion-page-content",
        'div[data-content-editable-leaf="true"]',
    ]
    goto_timeout = min(timeout_ms, 20000)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        if block_assets:
            def _route_handler(route, request):
                if request.resource_type in allowed_types:
                    route.continue_()
                else:
                    route.abort()

            page.route("**/*", _route_handler)

        try:
            page.goto(url, wait_until="networkidle", timeout=goto_timeout)
        except PlaywrightTimeoutError:
            pass

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
    """Render a JS-driven page and return HTML.

    Uses semaphore to limit concurrent browser instances and prevent
    resource exhaustion from too many simultaneous Playwright sessions.
    """
    # Acquire semaphore with timeout to prevent indefinite waiting
    acquired = _browser_semaphore.acquire(timeout=60)
    if not acquired:
        raise RuntimeError("Too many concurrent rendering requests. Please try again later.")

    try:
        try:
            html = _render_once(url, timeout_ms=timeout_ms, block_assets=True)
            if _is_rendered_html(html):
                return html
            html = _render_once(url, timeout_ms=timeout_ms + 5000, block_assets=False)
            if _is_rendered_html(html):
                return html
        except PlaywrightTimeoutError as exc:
            raise RuntimeError("Unable to render JS page within timeout") from exc
        raise RuntimeError("Unable to render JS page within timeout")
    finally:
        _browser_semaphore.release()
