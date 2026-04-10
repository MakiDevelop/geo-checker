"""Live AI Probe — query AI search engines to check URL citation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlparse

import requests

PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"
ENTITY_LABELS = {"PERSON", "ORG", "GPE", "PRODUCT"}
TITLE_SPLITTERS = (" | ", " - ", " – ", " — ", " :: ")


@dataclass
class ProbeQuery:
    query: str
    answer: str = ""
    citations: list[dict[str, str]] = field(default_factory=list)
    cited_target: bool = False
    cited_snippet: str = ""


@dataclass
class ProbeResult:
    target_url: str
    engine: Literal["perplexity"]
    queries: list[ProbeQuery]
    citation_rate: float = 0.0
    total_queries: int = 0
    cited_count: int = 0
    error: str = ""


def generate_probe_queries(parsed: dict[str, Any], *, limit: int = 3) -> list[str]:
    """Generate up to ``limit`` deduplicated probe queries from parsed content."""
    if limit <= 0:
        return []

    queries: list[str] = []
    seen: set[str] = set()

    meta = parsed.get("meta", {})
    title = _clean_topic(str(meta.get("title", "")))
    if title:
        _add_query(queries, seen, _build_what_is_query(title))

    headings = parsed.get("content", {}).get("headings", [])
    for heading in headings:
        if len(queries) >= limit:
            break
        if not isinstance(heading, dict):
            continue
        if heading.get("level") not in {"h1", "h2"}:
            continue
        heading_text = _clean_topic(str(heading.get("text", "")))
        if not heading_text:
            continue
        if heading_text.endswith("?"):
            _add_query(queries, seen, heading_text)
        else:
            _add_query(queries, seen, _build_what_is_query(heading_text))

    entities = parsed.get("entities", [])
    for entity in entities:
        if len(queries) >= limit:
            break
        if not isinstance(entity, dict):
            continue
        if entity.get("label") not in ENTITY_LABELS:
            continue
        entity_text = _clean_topic(str(entity.get("text", "")))
        if not entity_text:
            continue
        if title:
            query = f"How is {entity_text} related to {title}?"
        else:
            query = _build_what_is_query(entity_text)
        _add_query(queries, seen, query)

    return queries[:limit]


def probe_perplexity(
    target_url: str,
    queries: list[str],
    api_key: str,
    *,
    timeout: int = 30,
) -> ProbeResult:
    """Call the Perplexity API and detect whether the target URL is cited."""
    result = ProbeResult(
        target_url=target_url,
        engine="perplexity",
        queries=[],
        total_queries=len(queries),
    )
    target_domain = _extract_domain(target_url)

    for query in queries:
        probe_query = ProbeQuery(query=query)

        try:
            response = requests.post(
                PERPLEXITY_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "sonar",
                    "messages": [{"role": "user", "content": query}],
                    "return_citations": True,
                },
                timeout=timeout,
            )
        except requests.RequestException:
            probe_query.answer = "Perplexity request failed"
            result.queries.append(probe_query)
            continue

        if response.status_code == 401:
            result.error = "Invalid API key"
            return _finalize_result(result)

        if response.status_code == 429:
            result.error = "Rate limited by Perplexity"
            return _finalize_result(result)

        if response.status_code >= 400:
            probe_query.answer = f"Perplexity request failed ({response.status_code})"
            result.queries.append(probe_query)
            continue

        try:
            payload = response.json()
        except ValueError:
            probe_query.answer = "Perplexity returned an invalid response"
            result.queries.append(probe_query)
            continue

        probe_query.answer = _extract_answer(payload)
        probe_query.citations = _normalize_citations(payload.get("citations", []))

        matched_citation = next(
            (
                citation
                for citation in probe_query.citations
                if _domains_match(target_domain, _extract_domain(citation.get("url", "")))
            ),
            None,
        )
        if matched_citation is not None:
            probe_query.cited_target = True
            probe_query.cited_snippet = (
                matched_citation.get("snippet")
                or matched_citation.get("title")
                or matched_citation.get("url", "")
            )

        result.queries.append(probe_query)

    return _finalize_result(result)


def _extract_domain(url: str) -> str:
    """Extract the normalized domain from a URL without www. prefix or port."""
    if not url:
        return ""

    parsed = urlparse(url)
    domain = parsed.hostname or ""
    if domain.startswith("www."):
        domain = domain[4:]
    return domain.lower()


def _add_query(queries: list[str], seen: set[str], query: str) -> None:
    cleaned = " ".join(query.split()).strip()
    if not cleaned:
        return

    normalized = cleaned.casefold()
    if normalized in seen:
        return

    seen.add(normalized)
    queries.append(cleaned)


def _build_what_is_query(topic: str) -> str:
    cleaned = topic.rstrip("?.! ")
    return f"What is {cleaned}?" if cleaned else ""


def _clean_topic(value: str) -> str:
    cleaned = " ".join(value.split()).strip()
    if not cleaned:
        return ""

    for splitter in TITLE_SPLITTERS:
        if splitter in cleaned:
            cleaned = cleaned.split(splitter, 1)[0].strip()
            break

    return cleaned.strip(" -|:;,.")


def _domains_match(target_domain: str, citation_domain: str) -> bool:
    if not target_domain or not citation_domain:
        return False

    return (
        target_domain == citation_domain
        or citation_domain.endswith(f".{target_domain}")
        or target_domain.endswith(f".{citation_domain}")
    )


def _extract_answer(payload: dict[str, Any]) -> str:
    choices = payload.get("choices", [])
    if not choices or not isinstance(choices[0], dict):
        return ""

    message = choices[0].get("message", {})
    if not isinstance(message, dict):
        return ""

    content = message.get("content", "")
    if isinstance(content, str):
        return content

    return ""


def _finalize_result(result: ProbeResult) -> ProbeResult:
    result.cited_count = sum(1 for query in result.queries if query.cited_target)
    if result.total_queries > 0:
        result.citation_rate = round(result.cited_count / result.total_queries, 2)
    else:
        result.citation_rate = 0.0
    return result


def _normalize_citations(citations: Any) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    if not isinstance(citations, list):
        return normalized

    for citation in citations:
        if isinstance(citation, str):
            url = citation
            title = ""
            snippet = ""
        elif isinstance(citation, dict):
            url = str(
                citation.get("url")
                or citation.get("source")
                or citation.get("link")
                or ""
            )
            title = str(citation.get("title") or citation.get("name") or "")
            snippet = str(
                citation.get("snippet")
                or citation.get("text")
                or citation.get("description")
                or ""
            )
        else:
            continue

        if not (url or title or snippet):
            continue

        normalized.append(
            {
                "url": url,
                "title": title,
                "snippet": snippet,
            }
        )

    return normalized
