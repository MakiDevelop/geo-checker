"""JSON-LD Schema Generator — generate AI-friendly structured data."""
from __future__ import annotations

import json


def generate_article_schema(parsed: dict) -> dict:
    """Generate Article JSON-LD from parsed content."""
    meta = parsed.get("meta", {})
    author = parsed.get("author_info", {})
    freshness = parsed.get("freshness", {})
    stats = parsed.get("stats", {})

    schema: dict = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": meta.get("title", ""),
        "description": meta.get("description", ""),
    }

    # URL
    url = parsed.get("url", "")
    if url:
        schema["url"] = url
        schema["mainEntityOfPage"] = {
            "@type": "WebPage",
            "@id": url,
        }

    # Author
    author_name = author.get("name", "")
    if author_name:
        schema["author"] = {
            "@type": "Person",
            "name": author_name,
        }
        if author.get("url"):
            schema["author"]["url"] = author["url"]
    else:
        schema["author"] = {
            "@type": "Person",
            "name": "[Your Name]",
        }

    # Dates
    pub = freshness.get("date_published", "")
    mod = freshness.get("date_modified", "")
    if pub:
        schema["datePublished"] = pub
    if mod:
        schema["dateModified"] = mod

    # Word count
    wc = stats.get("word_count", 0)
    if wc > 0:
        schema["wordCount"] = wc

    return schema


def generate_faq_schema(parsed: dict) -> dict | None:
    """Generate FAQPage JSON-LD from Q&A headings.

    Only generates if Q&A structure is detected.
    """
    content = parsed.get("content", {})
    headings = content.get("headings", [])

    # Find question headings with answers
    faq_items = []
    for h in headings:
        text = h.get("text", "")
        paras = h.get("paragraphs", [])
        # Check if heading looks like a question
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
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": faq_items[:10],
    }


def generate_all_schemas(parsed: dict) -> list[dict]:
    """Generate all applicable JSON-LD schemas for the page."""
    schemas = []

    # Always generate Article schema
    schemas.append(generate_article_schema(parsed))

    # Generate FAQ if applicable
    faq = generate_faq_schema(parsed)
    if faq:
        schemas.append(faq)

    return schemas


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
