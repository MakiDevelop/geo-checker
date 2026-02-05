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
