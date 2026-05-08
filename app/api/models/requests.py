"""API request models."""
from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl, field_validator


class AnalyzeRequest(BaseModel):
    """Request body for URL analysis."""

    url: HttpUrl = Field(
        ...,
        description="The URL to analyze for GEO optimization",
        examples=["https://example.com/article"],
    )

    @field_validator("url")
    @classmethod
    def validate_url_scheme(cls, v: HttpUrl) -> HttpUrl:
        """Ensure URL uses http or https."""
        if str(v).startswith(("http://", "https://")):
            return v
        raise ValueError("Only http and https URLs are supported")


class UrlItem(BaseModel):
    """Single URL item for comparison."""

    id: str = Field(
        ...,
        pattern=r"^u\d+$",
        description="URL identifier (e.g., 'u1', 'u2')",
        examples=["u1"],
    )
    url: HttpUrl = Field(
        ...,
        description="The URL to analyze",
        examples=["https://example.com"],
    )


class CompareRequest(BaseModel):
    """Request body for multi-URL comparison."""

    urls: list[UrlItem] = Field(
        ...,
        min_length=2,
        max_length=3,
        description="List of URLs to compare (2-3 URLs)",
    )

    @field_validator("urls")
    @classmethod
    def validate_unique_ids(cls, v: list[UrlItem]) -> list[UrlItem]:
        """Ensure URL IDs are unique."""
        ids = [item.id for item in v]
        if len(ids) != len(set(ids)):
            raise ValueError("URL IDs must be unique")
        return v


class BrandAuditRequest(BaseModel):
    """Request body for brand visibility audit."""

    brand_name: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="Brand or product name to audit",
        examples=["GEO Checker"],
    )
    website_url: HttpUrl = Field(
        ...,
        description="Canonical website URL for the audited brand",
        examples=["https://gc.ranran.tw"],
    )
    region: str = Field(
        default="taiwan",
        min_length=2,
        max_length=40,
        description="Target market, e.g. taiwan, japan, or global",
    )
    language: str | None = Field(
        default=None,
        max_length=16,
        description="Optional answer language override, e.g. zh-TW or ja-JP",
    )
    competitors: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="Competitor brand names to compare against",
    )
    answer_texts: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Optional pasted answer-engine outputs for measured visibility",
    )
    category: str = Field(
        default="AI visibility / GEO",
        max_length=120,
        description="Category used in generated prompts",
    )
    use_case: str = Field(
        default="improve AI search visibility",
        max_length=160,
        description="Buyer problem or use case used in generated prompts",
    )

    @field_validator("brand_name", "region", "category", "use_case")
    @classmethod
    def validate_non_blank(cls, v: str) -> str:
        """Ensure required string fields are not whitespace."""
        clean_value = v.strip()
        if not clean_value:
            raise ValueError("Field cannot be blank")
        return clean_value

    @field_validator("competitors")
    @classmethod
    def validate_competitors(cls, v: list[str]) -> list[str]:
        """Remove blank competitors while preserving order."""
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in v:
            clean_item = item.strip()
            key = clean_item.casefold()
            if not clean_item or key in seen:
                continue
            cleaned.append(clean_item)
            seen.add(key)
        return cleaned

    @field_validator("answer_texts")
    @classmethod
    def validate_answer_texts(cls, v: list[str]) -> list[str]:
        """Remove blank pasted answers."""
        return [item.strip() for item in v if item.strip()]
