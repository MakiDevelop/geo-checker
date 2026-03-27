"""GEO Score Card Generator — shareable social media card image."""
from __future__ import annotations

from pathlib import Path

from jinja2 import Template

_TEMPLATE_PATH = Path("app/templates/score-card.html")


def _extract_card_data(result: dict) -> dict:
    """Extract data needed for the score card from analysis result."""
    geo = result.get("geo", {})
    score_data = geo.get("geo_score", {})
    breakdown = score_data.get("breakdown", {})
    ai_access = geo.get("ai_crawler_access", {})
    meta = result.get("meta", {})

    # Count crawler statuses
    crawlers = ai_access.get("crawlers", {})
    if crawlers:
        allowed = sum(
            1 for c in crawlers.values()
            if c.get("status") == "allow"
        )
        blocked = sum(
            1 for c in crawlers.values()
            if c.get("status") == "disallow"
        )
        total = len(crawlers)
    else:
        # Legacy format
        allowed = sum(
            1 for k in ("gptbot", "claudebot",
                         "perplexitybot", "google_extended")
            if ai_access.get(k) == "allow"
        )
        blocked = sum(
            1 for k in ("gptbot", "claudebot",
                         "perplexitybot", "google_extended")
            if ai_access.get(k) == "disallow"
        )
        total = 4

    return {
        "score": score_data.get("total", 0),
        "grade": score_data.get("grade", "?"),
        "grade_label": score_data.get("grade_label", ""),
        "url": result.get("url", ""),
        "title": meta.get("title", "Untitled"),
        "accessibility": breakdown.get(
            "accessibility", {},
        ).get("percentage", 0),
        "structure": breakdown.get(
            "structure", {},
        ).get("percentage", 0),
        "quality": breakdown.get(
            "quality", {},
        ).get("percentage", 0),
        "crawlers_allowed": allowed,
        "crawlers_blocked": blocked,
        "crawlers_total": total,
    }


def render_card_html(result: dict) -> str:
    """Render the score card as HTML string."""
    data = _extract_card_data(result)
    template_str = _TEMPLATE_PATH.read_text(encoding="utf-8")
    template = Template(template_str)
    return template.render(**data)


async def generate_card_image(
    result: dict, output_path: str,
) -> str:
    """Generate score card as PNG image using Playwright.

    Returns the output file path.
    """
    from playwright.async_api import async_playwright

    html = render_card_html(result)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(
            viewport={"width": 1200, "height": 630},
        )
        await page.set_content(html, wait_until="networkidle")
        await page.screenshot(path=output_path, type="png")
        await browser.close()

    return output_path


def generate_card_image_sync(
    result: dict, output_path: str,
) -> str:
    """Sync wrapper for card image generation."""
    from playwright.sync_api import sync_playwright

    html = render_card_html(result)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": 1200, "height": 630},
        )
        page.set_content(html, wait_until="networkidle")
        page.screenshot(path=output_path, type="png")
        browser.close()

    return output_path
