"""AI-Ready Badge Generator — dynamic SVG badges for embedding."""
from __future__ import annotations

_GRADE_COLORS = {
    "A": "#10b981",
    "B": "#22c55e",
    "C": "#f59e0b",
    "D": "#f97316",
    "F": "#ef4444",
}


def generate_badge_svg(
    score: int,
    grade: str,
    *,
    label: str = "GEO Score",
    style: str = "flat",
) -> str:
    """Generate a shields.io-style SVG badge.

    Args:
        score: GEO score 0-100
        grade: Letter grade A-F
        label: Left side label text
        style: "flat" or "rounded"
    """
    color = _GRADE_COLORS.get(grade, "#797588")
    value = f"{score}/100 ({grade})"

    label_width = len(label) * 7 + 16
    value_width = len(value) * 7 + 16
    total_width = label_width + value_width
    radius = "3" if style == "flat" else "10"

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="22">
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#fff" stop-opacity=".15"/>
    <stop offset="1" stop-opacity=".15"/>
  </linearGradient>
  <clipPath id="r">
    <rect width="{total_width}" height="22" rx="{radius}" fill="#fff"/>
  </clipPath>
  <g clip-path="url(#r)">
    <rect width="{label_width}" height="22" fill="#1b1c1c"/>
    <rect x="{label_width}" width="{value_width}" height="22" fill="{color}"/>
    <rect width="{total_width}" height="22" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle"
     font-family="Inter,Verdana,sans-serif"
     font-size="11" font-weight="600">
    <text x="{label_width / 2}" y="15">{label}</text>
    <text x="{label_width + value_width / 2}" y="15">{value}</text>
  </g>
</svg>"""


def generate_badge_html(
    score: int,
    grade: str,
    result_url: str,
) -> str:
    """Generate embeddable HTML snippet for the badge.

    Returns an <a><img> tag pointing to the badge endpoint.
    """
    badge_url = f"https://gc.ranran.tw/badge?url={result_url}"
    report_url = f"https://gc.ranran.tw/?url={result_url}"

    return (
        f'<a href="{report_url}" target="_blank" '
        f'rel="noopener" title="GEO Score: {score}/100 ({grade})">'
        f'<img src="{badge_url}" alt="GEO Score {score}" '
        f'height="22" /></a>'
    )
