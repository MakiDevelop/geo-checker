"""JSON-LD Schema Generator — @graph-connected, AI-friendly structured data."""
from __future__ import annotations

import json
from urllib.parse import urldefrag


def _make_id(url: str, fragment: str) -> str:
    """Build a fragment-based @id, stripping any existing fragment first."""
    base, _ = urldefrag(url)
    return f"{base}#{fragment}"


def generate_article_schema(parsed: dict) -> dict:
    """Generate Article node for @graph."""
    meta = parsed.get("meta", {})
    author = parsed.get("author_info", {})
    freshness = parsed.get("freshness", {})
    stats = parsed.get("stats", {})

    url = parsed.get("url", "")
    schema: dict = {
        "@type": "Article",
        "headline": meta.get("title", ""),
        "description": meta.get("description", ""),
    }

    if url:
        schema["@id"] = _make_id(url, "article")
        schema["url"] = url
        schema["mainEntityOfPage"] = {"@id": url}
        schema["isPartOf"] = {"@id": _make_id(url, "website")}

    author_name = author.get("name", "")
    if author_name:
        schema["author"] = {"@id": _make_id(url, "author")} if url else {
            "@type": "Person",
            "name": author_name,
        }
    else:
        schema["author"] = {
            "@type": "Person",
            "name": "[Your Name]",
        }

    pub = freshness.get("date_published", "")
    mod = freshness.get("date_modified", "")
    if pub:
        schema["datePublished"] = pub
    if mod:
        schema["dateModified"] = mod

    wc = stats.get("word_count", 0)
    if wc > 0:
        schema["wordCount"] = wc

    return schema


def generate_person_schema(parsed: dict) -> dict | None:
    """Generate Person node for @graph (author E-E-A-T)."""
    author = parsed.get("author_info", {})
    author_name = author.get("name", "")
    if not author_name:
        return None

    url = parsed.get("url", "")
    schema: dict = {
        "@type": "Person",
        "name": author_name,
    }
    if url:
        schema["@id"] = _make_id(url, "author")
    if author.get("url"):
        schema["url"] = author["url"]

    return schema


def generate_organization_schema(parsed: dict) -> dict | None:
    """Generate Organization node for @graph."""
    schema_org = parsed.get("schema_org", {})
    for s in schema_org.get("schemas", []):
        if s.get("type") in ("Organization", "Corporation"):
            data = s.get("data", {})
            org: dict = {
                "@type": data.get("@type", "Organization"),
                "name": data.get("name", ""),
            }
            url = parsed.get("url", "")
            if url:
                org["@id"] = _make_id(url, "organization")
            if data.get("url"):
                org["url"] = data["url"]
            same_as = data.get("sameAs", [])
            if isinstance(same_as, str):
                same_as = [same_as]
            if same_as:
                org["sameAs"] = same_as
            return org
    return None


def generate_faq_schema(parsed: dict) -> dict | None:
    """Generate FAQPage JSON-LD from Q&A headings."""
    content = parsed.get("content", {})
    headings = content.get("headings", [])

    faq_items = []
    for h in headings:
        text = h.get("text", "")
        paras = h.get("paragraphs", [])
        if (text.endswith("?") or text.endswith("？")) and paras:
            faq_items.append({
                "@type": "Question",
                "name": text,
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": paras[0][:500],
                },
            })

    if len(faq_items) < 2:
        return None

    return {
        "@type": "FAQPage",
        "mainEntity": faq_items[:10],
    }


def generate_all_schemas(parsed: dict) -> list[dict]:
    """Generate @graph-connected JSON-LD schemas.

    Uses @graph to link Article → Person (author) → Organization,
    giving AI systems multiple entity extraction pathways.
    """
    graph_nodes = []

    article = generate_article_schema(parsed)
    graph_nodes.append(article)

    person = generate_person_schema(parsed)
    if person:
        graph_nodes.append(person)

    org = generate_organization_schema(parsed)
    if org:
        graph_nodes.append(org)

    faq = generate_faq_schema(parsed)
    if faq:
        graph_nodes.append(faq)

    if len(graph_nodes) >= 2:
        return [{
            "@context": "https://schema.org",
            "@graph": graph_nodes,
        }]

    for node in graph_nodes:
        node["@context"] = "https://schema.org"
    return graph_nodes


def schemas_to_html(schemas: list[dict]) -> str:
    """Convert schemas to embeddable HTML script tags."""
    parts = []
    for schema in schemas:
        json_str = json.dumps(schema, ensure_ascii=False, indent=2)
        parts.append(
            f'<script type="application/ld+json">\n'
            f'{json_str}\n'
            f'</script>'
        )
    return "\n\n".join(parts)
