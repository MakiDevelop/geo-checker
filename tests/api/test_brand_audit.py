"""Tests for the /api/v1/brand-audit endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset API rate limiter between tests."""
    from app.api.v1.deps import api_rate_limiter

    api_rate_limiter._requests.clear()
    yield
    api_rate_limiter._requests.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_brand_audit_returns_prompt_pack_and_visibility(client: TestClient) -> None:
    response = client.post(
        "/api/v1/brand-audit",
        json={
            "brand_name": "GEO Checker",
            "website_url": "https://gc.ranran.tw",
            "region": "taiwan",
            "competitors": ["Otterly", "KIME"],
            "category": "GEO 工具",
            "use_case": "追蹤 AI 搜尋能見度",
            "answer_texts": [
                "GEO Checker 適合台灣 CJK 市場，Otterly 偏向海外。",
                "KIME 與 Otterly 都能做 AI visibility tracking。",
            ],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["brand_name"] == "GEO Checker"
    assert data["language"] == "zh-TW"
    assert len(data["prompts"]) == 5
    assert data["visibility"][0]["mention_count"] == 1
    assert data["visibility"][0]["mention_rate"] == 0.5
    assert "# Brand Visibility Audit: GEO Checker" in data["markdown_report"]


def test_brand_audit_rejects_blank_brand(client: TestClient) -> None:
    response = client.post(
        "/api/v1/brand-audit",
        json={
            "brand_name": " ",
            "website_url": "https://gc.ranran.tw",
        },
    )

    assert response.status_code == 422
