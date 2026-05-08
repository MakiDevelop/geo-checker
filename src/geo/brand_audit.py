"""Brand visibility audit helpers for GEO/AIO market validation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_REGION_QUERIES = {
    "taiwan": {
        "label": "Taiwan",
        "language": "zh-TW",
        "templates": [
            "在台灣，{category} 有哪些推薦品牌？",
            "{brand} 是做什麼的？適合哪些使用情境？",
            "{brand} 和 {competitor} 差異是什麼？",
            "如果我要解決 {use_case}，有哪些台灣可用的方案？",
            "請用繁體中文比較 {brand} 與其他 {category} 服務。",
        ],
    },
    "japan": {
        "label": "Japan",
        "language": "ja-JP",
        "templates": [
            "日本で使える{category}のおすすめブランドは？",
            "{brand}は何を提供していて、どんな用途に向いていますか？",
            "{brand}と{competitor}の違いは何ですか？",
            "{use_case}を解決する日本向けの選択肢を比較してください。",
            "{brand}を他の{category}サービスと日本語で比較してください。",
        ],
    },
}

GENERIC_TEMPLATES = [
    "What are the best {category} options for {use_case}?",
    "What does {brand} do, and who is it for?",
    "How does {brand} compare with {competitor}?",
    "Which companies should I evaluate for {use_case}?",
    "Summarize {brand} and cite the most useful sources.",
]


@dataclass(frozen=True)
class VisibilityEntity:
    """Mention visibility for one brand/entity in pasted AI answers."""

    name: str
    is_target: bool
    mention_count: int
    answer_count: int
    mention_rate: float
    average_position: float | None


@dataclass(frozen=True)
class BrandAudit:
    """Deterministic brand visibility audit result."""

    brand_name: str
    website_url: str
    region: str
    language: str
    category: str
    use_case: str
    prompts: list[str]
    visibility: list[VisibilityEntity]
    top_fixes: list[dict[str, str]]
    markdown_report: str

    def to_dict(self) -> dict[str, Any]:
        """Convert audit result to an API-friendly dict."""
        return {
            "brand_name": self.brand_name,
            "website_url": self.website_url,
            "region": self.region,
            "language": self.language,
            "category": self.category,
            "use_case": self.use_case,
            "prompts": self.prompts,
            "visibility": [
                {
                    "name": item.name,
                    "is_target": item.is_target,
                    "mention_count": item.mention_count,
                    "answer_count": item.answer_count,
                    "mention_rate": item.mention_rate,
                    "average_position": item.average_position,
                }
                for item in self.visibility
            ],
            "top_fixes": self.top_fixes,
            "markdown_report": self.markdown_report,
        }


def build_brand_audit(
    *,
    brand_name: str,
    website_url: str,
    region: str = "taiwan",
    language: str | None = None,
    competitors: list[str] | None = None,
    answer_texts: list[str] | None = None,
    category: str = "AI visibility / GEO",
    use_case: str = "improve AI search visibility",
) -> BrandAudit:
    """Build a deterministic CJK-first brand visibility audit.

    `answer_texts` are optional pasted outputs from ChatGPT, Perplexity,
    Gemini, or other answer engines. When absent, the audit still returns a
    prompt pack and implementation fixes so a sales/demo workflow can start.
    """
    clean_brand = brand_name.strip()
    clean_competitors = _dedupe_names(competitors or [], exclude={clean_brand})
    clean_answers = [text.strip() for text in (answer_texts or []) if text.strip()]
    resolved_region = region.strip().lower() or "global"
    resolved_language = language or _default_language(resolved_region)
    resolved_category = category.strip() or "AI visibility / GEO"
    resolved_use_case = use_case.strip() or "improve AI search visibility"

    prompts = build_prompt_pack(
        brand_name=clean_brand,
        region=resolved_region,
        competitors=clean_competitors,
        category=resolved_category,
        use_case=resolved_use_case,
    )
    entities = [clean_brand, *clean_competitors]
    visibility = score_visibility(entities, clean_answers, target=clean_brand)
    top_fixes = recommend_fixes(
        brand_name=clean_brand,
        website_url=website_url,
        has_answers=bool(clean_answers),
        target_visibility=visibility[0] if visibility else None,
    )
    markdown_report = render_markdown_report(
        brand_name=clean_brand,
        website_url=website_url,
        region=resolved_region,
        language=resolved_language,
        prompts=prompts,
        visibility=visibility,
        top_fixes=top_fixes,
        has_answers=bool(clean_answers),
    )

    return BrandAudit(
        brand_name=clean_brand,
        website_url=website_url,
        region=resolved_region,
        language=resolved_language,
        category=resolved_category,
        use_case=resolved_use_case,
        prompts=prompts,
        visibility=visibility,
        top_fixes=top_fixes,
        markdown_report=markdown_report,
    )


def build_prompt_pack(
    *,
    brand_name: str,
    region: str,
    competitors: list[str],
    category: str,
    use_case: str,
) -> list[str]:
    """Generate localized prompts for answer-engine visibility checks."""
    config = DEFAULT_REGION_QUERIES.get(region.lower())
    templates = config["templates"] if config else GENERIC_TEMPLATES
    competitor = competitors[0] if competitors else "主要競品"

    return [
        template.format(
            brand=brand_name,
            competitor=competitor,
            category=category,
            use_case=use_case,
        )
        for template in templates
    ]


def score_visibility(
    entity_names: list[str],
    answer_texts: list[str],
    *,
    target: str,
) -> list[VisibilityEntity]:
    """Score entity mentions across answer texts."""
    total_answers = len(answer_texts)
    normalized_answers = [_normalize(text) for text in answer_texts]
    results: list[VisibilityEntity] = []

    for name in _dedupe_names(entity_names):
        normalized_name = _normalize(name)
        positions: list[int] = []
        mention_count = 0

        for answer in normalized_answers:
            position = answer.find(normalized_name)
            if position >= 0:
                mention_count += 1
                positions.append(position + 1)

        mention_rate = mention_count / total_answers if total_answers else 0.0
        average_position = round(sum(positions) / len(positions), 1) if positions else None
        results.append(
            VisibilityEntity(
                name=name,
                is_target=_normalize(name) == _normalize(target),
                mention_count=mention_count,
                answer_count=total_answers,
                mention_rate=round(mention_rate, 4),
                average_position=average_position,
            )
        )

    return results


def recommend_fixes(
    *,
    brand_name: str,
    website_url: str,
    has_answers: bool,
    target_visibility: VisibilityEntity | None,
) -> list[dict[str, str]]:
    """Return pragmatic fixes ordered by expected demo impact."""
    fixes: list[dict[str, str]] = []
    visibility_rate = target_visibility.mention_rate if target_visibility else 0.0

    if not has_answers:
        fixes.append(
            {
                "priority": "critical",
                "action": (
                    "Run the prompt pack in ChatGPT, Perplexity, Gemini, and "
                    "Google AI Mode; paste answers back into this audit."
                ),
                "impact": "Turns the audit from readiness planning into measured visibility.",
            }
        )
    elif visibility_rate < 0.5:
        fixes.append(
            {
                "priority": "critical",
                "action": (
                    f"Add a concise '{brand_name} is ...' entity block near "
                    f"the top of {website_url}."
                ),
                "impact": "Improves brand extraction when answer engines summarize the page.",
            }
        )
    else:
        fixes.append(
            {
                "priority": "recommended",
                "action": "Preserve the current entity framing and add third-party proof sources.",
                "impact": "Raises citation confidence beyond simple brand mentions.",
            }
        )

    fixes.extend(
        [
            {
                "priority": "recommended",
                "action": "Publish localized comparison pages for Taiwan/Japan search intents.",
                "impact": "Captures non-English category and competitor prompts.",
            },
            {
                "priority": "recommended",
                "action": (
                    "Add Organization, WebSite, FAQPage, and BreadcrumbList "
                    "JSON-LD where relevant."
                ),
                "impact": "Gives answer engines stable structured facts to quote.",
            },
            {
                "priority": "suggested",
                "action": (
                    "Create /llms.txt with canonical product, pricing, docs, "
                    "and support URLs."
                ),
                "impact": "Makes preferred source paths explicit for AI crawlers.",
            },
            {
                "priority": "suggested",
                "action": (
                    "Collect independent mentions from docs, partner pages, "
                    "case studies, or directories."
                ),
                "impact": "Reduces dependence on self-authored claims.",
            },
        ]
    )
    return fixes


def render_markdown_report(
    *,
    brand_name: str,
    website_url: str,
    region: str,
    language: str,
    prompts: list[str],
    visibility: list[VisibilityEntity],
    top_fixes: list[dict[str, str]],
    has_answers: bool,
) -> str:
    """Render a compact Markdown report for sales/demo workflows."""
    lines = [
        f"# Brand Visibility Audit: {brand_name}",
        "",
        f"- Website: {website_url}",
        f"- Region: {region}",
        f"- Language: {language}",
        f"- Mode: {'measured answers' if has_answers else 'prompt pack only'}",
        "",
        "## Visibility",
        "",
        "| Entity | Mentions | Mention rate | Avg. position |",
        "|---|---:|---:|---:|",
    ]
    for item in visibility:
        avg_position = "-" if item.average_position is None else str(item.average_position)
        lines.append(
            f"| {item.name} | {item.mention_count}/{item.answer_count} | "
            f"{item.mention_rate:.0%} | {avg_position} |"
        )

    lines.extend(["", "## Prompt Pack", ""])
    lines.extend(f"{index}. {prompt}" for index, prompt in enumerate(prompts, start=1))

    lines.extend(["", "## Top Fixes", ""])
    lines.extend(
        f"- [{fix['priority']}] {fix['action']} Impact: {fix['impact']}"
        for fix in top_fixes
    )
    return "\n".join(lines)


def _default_language(region: str) -> str:
    config = DEFAULT_REGION_QUERIES.get(region)
    if config:
        return str(config["language"])
    return "en"


def _dedupe_names(names: list[str], exclude: set[str] | None = None) -> list[str]:
    exclude_normalized = {_normalize(item) for item in (exclude or set())}
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        clean_name = name.strip()
        normalized = _normalize(clean_name)
        if not clean_name or normalized in seen or normalized in exclude_normalized:
            continue
        seen.add(normalized)
        result.append(clean_name)
    return result


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())
