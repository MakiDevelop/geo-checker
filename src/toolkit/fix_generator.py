"""Generate copy-pasteable fixes from GEO analysis results."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.toolkit.robots_generator import generate_robots_txt
from src.toolkit.schema_generator import generate_all_schemas, schemas_to_html


@dataclass
class FixSnippet:
    """A single copy-pasteable fix recommendation."""

    category: Literal["robots_txt", "schema_markup", "meta_tags", "server_config", "content"]
    priority: Literal["critical", "recommended", "suggested"]
    title: str
    current_value: str
    explanation: str
    code_snippet: str
    file_hint: str


def generate_fixes(geo_result: dict, parsed: dict, *, url: str = "") -> list[FixSnippet]:
    """Generate ordered fix snippets from GEO analysis output."""
    fixes: list[FixSnippet] = []

    effective_url = url or parsed.get("url", "")
    blocked_crawlers = _blocked_crawlers(geo_result)
    if blocked_crawlers:
        current_value = ", ".join(
            f"{crawler['display']}: {crawler['status']}" for crawler in blocked_crawlers
        )
        fixes.append(
            FixSnippet(
                category="robots_txt",
                priority="critical",
                title="Allow blocked AI crawlers in robots.txt",
                current_value=current_value,
                explanation=(
                    "AI search and answer engines cannot reliably read this page while "
                    "their crawlers are explicitly blocked."
                ),
                code_snippet=generate_robots_txt(geo_result, url=effective_url),
                file_hint="robots.txt",
            )
        )
        fixes.append(
            FixSnippet(
                category="server_config",
                priority="suggested",
                title="Ensure nginx does not block AI crawler user agents",
                current_value=current_value,
                explanation=(
                    "Some sites allow crawlers in robots.txt but still block them at the "
                    "reverse-proxy layer. Keep nginx rules neutral for AI crawler UAs."
                ),
                code_snippet=(
                    "# Allow AI crawlers\n"
                    "if ($http_user_agent ~* \"(GPTBot|ClaudeBot|PerplexityBot)\") {\n"
                    "    # Do not block\n"
                    "}\n"
                ),
                file_hint="nginx.conf",
            )
        )

    noindex_value = _noindex_value(geo_result)
    if noindex_value:
        fixes.append(
            FixSnippet(
                category="meta_tags",
                priority="critical",
                title="Remove noindex directives",
                current_value=noindex_value,
                explanation=(
                    "A noindex directive tells crawlers not to index the page, which makes "
                    "AI retrieval and citation much less likely."
                ),
                code_snippet='<meta name="robots" content="index, follow">',
                file_hint="<head>",
            )
        )

    if _missing_schema(parsed):
        fixes.append(
            FixSnippet(
                category="schema_markup",
                priority="recommended",
                title="Add Schema.org JSON-LD",
                current_value="missing",
                explanation=(
                    "Structured data gives AI systems an explicit content model and reduces "
                    "semantic ambiguity when summarizing the page."
                ),
                code_snippet=schemas_to_html(generate_all_schemas(parsed)),
                file_hint="<head>",
            )
        )

    meta = parsed.get("meta", {})
    author_info = parsed.get("author_info", {})
    freshness = parsed.get("freshness", {})

    if not author_info.get("has_author"):
        fixes.append(
            FixSnippet(
                category="meta_tags",
                priority="recommended",
                title="Add author metadata",
                current_value="missing",
                explanation=(
                    "Author signals help AI systems judge who is speaking and improve "
                    "E-E-A-T interpretation."
                ),
                code_snippet='<meta name="author" content="Your Name">',
                file_hint="<head>",
            )
        )

    if not freshness.get("has_dates"):
        fixes.append(
            FixSnippet(
                category="meta_tags",
                priority="recommended",
                title="Add publication date metadata",
                current_value="missing",
                explanation=(
                    "Explicit publication and update dates help AI systems reason about "
                    "freshness and citation recency."
                ),
                code_snippet=(
                    '<meta property="article:published_time" '
                    'content="2026-01-01T00:00:00Z">\n'
                    '<meta property="article:modified_time" '
                    'content="2026-01-01T00:00:00Z">'
                ),
                file_hint="<head>",
            )
        )

    if not meta.get("description", "").strip():
        fixes.append(
            FixSnippet(
                category="meta_tags",
                priority="recommended",
                title="Add a descriptive meta description",
                current_value="missing",
                explanation=(
                    "A concise description improves narrative framing and gives AI systems "
                    "a strong summary hint before reading the body content."
                ),
                code_snippet=(
                    f'<meta name="description" content="{_suggest_description(parsed)}">'
                ),
                file_hint="<head>",
            )
        )

    priority_order = {"critical": 0, "recommended": 1, "suggested": 2}
    fixes.sort(key=lambda item: (priority_order[item.priority], item.title))
    return fixes


def _blocked_crawlers(geo_result: dict) -> list[dict]:
    ai_access = geo_result.get("ai_crawler_access", {})
    blocked = []
    for crawler_key, info in ai_access.get("crawlers", {}).items():
        if info.get("status") == "disallow":
            blocked.append(
                {
                    "crawler_key": crawler_key,
                    "display": info.get("display", crawler_key),
                    "status": info.get("status", "unspecified"),
                }
            )
    return blocked


def _noindex_value(geo_result: dict) -> str:
    ai_access = geo_result.get("ai_crawler_access", {})
    current_values = []

    meta_robots = ai_access.get("meta_robots", {})
    if meta_robots.get("noindex"):
        current_values.append(meta_robots.get("content", "noindex"))

    x_robots = ai_access.get("x_robots_tag", {})
    if x_robots.get("noindex"):
        current_values.append(x_robots.get("value", "noindex"))

    return " | ".join(value for value in current_values if value)


def _missing_schema(parsed: dict) -> bool:
    schema_org = parsed.get("schema_org", {})
    return not schema_org.get("available") or not schema_org.get("types_found")


def _suggest_description(parsed: dict) -> str:
    meta = parsed.get("meta", {})
    title = str(meta.get("title", "")).strip()
    paragraphs = parsed.get("content", {}).get("paragraphs", [])
    source = paragraphs[0] if paragraphs else title or "Add a concise summary of this page."
    cleaned = " ".join(str(source).split())
    if len(cleaned) > 155:
        cleaned = cleaned[:152].rstrip() + "..."
    return cleaned.replace('"', "&quot;")
