"""Tests for the /api/v1/probe endpoint."""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

if "cachetools" not in sys.modules:
    cachetools = types.ModuleType("cachetools")

    class TTLCache(dict):
        def __init__(self, *args, **kwargs):
            super().__init__()

    cachetools.TTLCache = TTLCache
    sys.modules["cachetools"] = cachetools

if "readability" not in sys.modules:
    readability = types.ModuleType("readability")

    class Document:
        def __init__(self, html: str):
            self.html = html

        def summary(self, html_partial: bool = True) -> str:
            return self.html

    readability.Document = Document
    sys.modules["readability"] = readability

if "playwright.sync_api" not in sys.modules:
    playwright = types.ModuleType("playwright")
    sync_api = types.ModuleType("playwright.sync_api")

    class PlaywrightTimeoutError(Exception):
        pass

    def sync_playwright():
        raise RuntimeError("playwright is not available in test environment")

    sync_api.TimeoutError = PlaywrightTimeoutError
    sync_api.sync_playwright = sync_playwright
    playwright.sync_api = sync_api
    sys.modules["playwright"] = playwright
    sys.modules["playwright.sync_api"] = sync_api

from app.main import app
from src.ai.live_probe import ProbeQuery, ProbeResult


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset the API rate limiter before and after each test.

    Probe endpoint is now rate-limited (to prevent abuse as a paid-API proxy),
    so shared-state accumulation across tests would cause 429s.
    """
    from app.api.v1.deps import api_rate_limiter

    api_rate_limiter._requests.clear()
    yield
    api_rate_limiter._requests.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def results_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "results"
    monkeypatch.setattr("app.api.v1.endpoints.probe.RESULTS_DIR", path)
    return path


def _write_result(results_dir: Path, result_id: str) -> None:
    results_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "analysis_id": result_id,
        "url": "https://example.com/article",
        "meta": {"title": "Example GEO Page", "description": "", "canonical": ""},
        "content": {
            "headings": [{"level": "h1", "text": "Example GEO Page", "paragraphs": []}],
            "paragraphs": ["Example paragraph about GEO visibility."],
            "lists": [],
            "tables": [],
            "blocks": [],
        },
        "entities": [{"text": "Perplexity", "label": "ORG"}],
    }
    (results_dir / f"{result_id}.json").write_text(json.dumps(payload))


def test_probe_missing_header(client: TestClient) -> None:
    response = client.post("/api/v1/probe", json={"result_id": "a" * 32})

    assert response.status_code == 422


def test_probe_invalid_key_format(client: TestClient) -> None:
    response = client.post(
        "/api/v1/probe",
        json={"result_id": "a" * 32},
        headers={"X-Perplexity-Key": "invalid-key"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error"]["code"] == "INVALID_KEY_FORMAT"


def test_probe_missing_identifier(client: TestClient) -> None:
    response = client.post(
        "/api/v1/probe",
        json={},
        headers={"X-Perplexity-Key": "pplx-test-key"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error"]["code"] == "MISSING_IDENTIFIER"


def test_probe_result_id_not_found(client: TestClient, results_dir: Path) -> None:
    response = client.post(
        "/api/v1/probe",
        json={"result_id": "b" * 32},
        headers={"X-Perplexity-Key": "pplx-test-key"},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["error"]["code"] == "RESULT_NOT_FOUND"


def test_probe_result_id_path_traversal(client: TestClient) -> None:
    response = client.post(
        "/api/v1/probe",
        json={"result_id": "../../etc/passwd"},
        headers={"X-Perplexity-Key": "pplx-test-key"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error"]["code"] == "INVALID_REQUEST"


def test_probe_success(client: TestClient, results_dir: Path) -> None:
    result_id = "c" * 32
    _write_result(results_dir, result_id)
    probe_result = ProbeResult(
        target_url="https://example.com/article",
        engine="perplexity",
        queries=[
            ProbeQuery(
                query="What is Example GEO Page?",
                answer="Example answer",
                citations=[
                    {
                        "url": "https://example.com/article",
                        "title": "Example",
                        "snippet": "",
                    }
                ],
                cited_target=True,
                cited_snippet="Example answer",
            )
        ],
        citation_rate=1.0,
        total_queries=1,
        cited_count=1,
    )

    with patch("app.api.v1.endpoints.probe.probe_perplexity", return_value=probe_result):
        response = client.post(
            "/api/v1/probe",
            json={"result_id": result_id},
            headers={"X-Perplexity-Key": "pplx-test-key"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["target_url"] == "https://example.com/article"
    assert data["engine"] == "perplexity"
    assert data["cited_count"] == 1
    assert data["total_queries"] == 1
    assert data["queries"][0]["query"] == "What is Example GEO Page?"


def test_probe_key_not_in_response(client: TestClient, results_dir: Path) -> None:
    result_id = "d" * 32
    key = "pplx-secret-123456"
    _write_result(results_dir, result_id)
    probe_result = ProbeResult(
        target_url="https://example.com/article",
        engine="perplexity",
        queries=[],
        citation_rate=0.0,
        total_queries=0,
        cited_count=0,
    )

    with patch("app.api.v1.endpoints.probe.probe_perplexity", return_value=probe_result):
        response = client.post(
            "/api/v1/probe",
            json={"result_id": result_id},
            headers={"X-Perplexity-Key": key},
        )

    assert response.status_code == 200
    assert key not in response.text


def test_probe_registered_in_openapi(client: TestClient) -> None:
    response = client.get("/api/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/probe" in response.json()["paths"]
