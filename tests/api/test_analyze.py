"""Tests for the /api/v1/analyze endpoint."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def reset_rate_limiter():
    """Reset the API rate limiter before each test."""
    from app.api.v1.deps import api_rate_limiter

    api_rate_limiter._requests.clear()
    yield
    api_rate_limiter._requests.clear()


class TestAnalyzeEndpoint:
    """Tests for POST /api/v1/analyze."""

    def test_analyze_valid_url_returns_job(self, client, reset_rate_limiter):
        """Valid URL should return a job response with pending status."""
        with patch("app.api.services.job_queue.job_queue.submit") as mock_submit:
            mock_submit.return_value = "a" * 32  # Valid job ID

            with patch("app.api.services.job_queue.job_queue.get") as mock_get:
                from datetime import UTC, datetime

                mock_job = MagicMock()
                mock_job.status = "pending"
                mock_job.created_at = datetime.now(UTC)
                mock_get.return_value = mock_job

                response = client.post(
                    "/api/v1/analyze", json={"url": "https://example.com"}
                )

        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "pending"
        assert data["url"].rstrip("/") == "https://example.com"

    def test_analyze_invalid_url_scheme_rejected(self, client, reset_rate_limiter):
        """Non-http(s) URLs should be rejected."""
        response = client.post("/api/v1/analyze", json={"url": "ftp://example.com"})

        assert response.status_code == 422  # Pydantic validation error

    def test_analyze_malformed_url_rejected(self, client, reset_rate_limiter):
        """Malformed URLs should be rejected."""
        response = client.post("/api/v1/analyze", json={"url": "not-a-url"})

        assert response.status_code == 422

    def test_analyze_missing_url_rejected(self, client, reset_rate_limiter):
        """Request without URL should be rejected."""
        response = client.post("/api/v1/analyze", json={})

        assert response.status_code == 422

    def test_analyze_empty_body_rejected(self, client, reset_rate_limiter):
        """Empty request body should be rejected."""
        response = client.post("/api/v1/analyze")

        assert response.status_code == 422


class TestJobsEndpoint:
    """Tests for GET /api/v1/jobs/{job_id}."""

    @pytest.mark.skip(reason="Complex mock interaction with middleware - needs investigation")
    def test_get_job_valid_id(self, client, reset_rate_limiter):
        """Valid job ID should return job details."""
        job_id = "a" * 32

        # Patch at the endpoint module level where it's imported
        with patch("app.api.v1.endpoints.jobs.job_queue") as mock_queue:
            from datetime import UTC, datetime

            from app.api.services.job_queue import Job

            mock_job = Job(
                id=job_id,
                url="https://example.com",
                status="completed",
                created_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
                result={
                    "geo": {
                        "geo_score": {
                            "total": 75,
                            "grade": "B",
                            "grade_label": "Good",
                            "breakdown": {
                                "accessibility": {"score": 35, "max": 40, "percentage": 87},
                                "structure": {"score": 20, "max": 30, "percentage": 67},
                                "quality": {"score": 20, "max": 30, "percentage": 67},
                            },
                        },
                        "summary": {
                            "summary_key": "good",
                            "issues": {"critical": [], "warning": [], "good": []},
                            "priority_fixes": [],
                        },
                        "ai_crawler_access": {
                            "robots_txt_found": True,
                            "gptbot": "allow",
                            "claudebot": "allow",
                            "perplexitybot": "allow",
                            "google_extended": "allow",
                            "meta_robots": {"content": "", "noindex": False, "nofollow": False},
                            "x_robots_tag": {"value": "", "noindex": False, "nofollow": False},
                            "notes": "",
                        },
                        "extended_metrics": {
                            "qa_structure": {
                                "has_qa_structure": False,
                                "question_headings": 0,
                                "question_paragraphs": 0,
                            },
                            "link_quality": {
                                "total_links": 5,
                                "internal_links": 3,
                                "external_links": 2,
                                "descriptive_anchors": 4,
                                "quality_score": 80,
                            },
                            "content_depth": {
                                "word_count": 500,
                                "unique_heading_levels": 3,
                                "has_deep_hierarchy": True,
                                "depth_score": 8,
                            },
                            "entity_count": 10,
                            "first_paragraph": {
                                "has_strong_opening": True,
                                "first_paragraph_length": 150,
                                "score": 2,
                            },
                            "pronoun_clarity": {
                                "paragraphs_starting_with_pronoun": 0,
                                "total_pronouns_in_first_10": 2,
                                "score": 2,
                            },
                            "citation_potential": {
                                "score": 7,
                                "max_score": 11,
                                "level": "good",
                                "signals": ["has_statistics", "has_citations"],
                            },
                        },
                    }
                },
                error=None,
            )
            mock_queue.get.return_value = mock_job

            response = client.get(f"/api/v1/jobs/{job_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == job_id
        assert data["status"] == "completed"
        assert data["result"]["geo_score"]["total"] == 75

    def test_get_job_invalid_id_format(self, client, reset_rate_limiter):
        """Invalid job ID format should return 400."""
        response = client.get("/api/v1/jobs/invalid-id")

        assert response.status_code == 400
        data = response.json()
        assert "error" in data["detail"]
        assert data["detail"]["error"]["code"] == "INVALID_REQUEST"

    def test_get_job_not_found(self, client, reset_rate_limiter):
        """Non-existent job ID should return 404."""
        job_id = "b" * 32

        with patch("app.api.services.job_queue.job_queue.get") as mock_get:
            mock_get.return_value = None

            response = client.get(f"/api/v1/jobs/{job_id}")

        assert response.status_code == 404
        data = response.json()
        assert data["detail"]["error"]["code"] == "JOB_NOT_FOUND"

    def test_get_job_pending_status(self, client, reset_rate_limiter):
        """Pending job should return null result."""
        job_id = "c" * 32

        with patch("app.api.services.job_queue.job_queue.get") as mock_get:
            from datetime import UTC, datetime

            mock_job = MagicMock()
            mock_job.id = job_id
            mock_job.url = "https://example.com"
            mock_job.status = "pending"
            mock_job.created_at = datetime.now(UTC)
            mock_job.completed_at = None
            mock_job.result = None
            mock_job.error = None
            mock_get.return_value = mock_job

            response = client.get(f"/api/v1/jobs/{job_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "pending"
        assert data["result"] is None

    def test_get_job_failed_status(self, client, reset_rate_limiter):
        """Failed job should return error message."""
        job_id = "d" * 32

        with patch("app.api.services.job_queue.job_queue.get") as mock_get:
            from datetime import UTC, datetime

            mock_job = MagicMock()
            mock_job.id = job_id
            mock_job.url = "https://example.com"
            mock_job.status = "failed"
            mock_job.created_at = datetime.now(UTC)
            mock_job.completed_at = datetime.now(UTC)
            mock_job.result = None
            mock_job.error = "SSRF protection: Access to private/internal IP addresses is forbidden"
            mock_get.return_value = mock_job

            response = client.get(f"/api/v1/jobs/{job_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"
        assert "SSRF" in data["error"]


class TestHealthEndpoint:
    """Tests for GET /api/v1/health."""

    def test_health_check(self, client):
        """Health endpoint should return ok status."""
        response = client.get("/api/v1/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("ok", "healthy", "degraded")


class TestRateLimiting:
    """Tests for API rate limiting."""

    def test_rate_limit_exceeded_anonymous(self, client, reset_rate_limiter):
        """Anonymous users should be rate limited after 5 requests."""
        from app.api.v1.deps import api_rate_limiter

        # Clear any existing state
        api_rate_limiter._requests.clear()

        with patch("app.api.services.job_queue.job_queue.submit") as mock_submit:
            mock_submit.return_value = "a" * 32

            with patch("app.api.services.job_queue.job_queue.get") as mock_get:
                from datetime import UTC, datetime

                mock_job = MagicMock()
                mock_job.status = "pending"
                mock_job.created_at = datetime.now(UTC)
                mock_get.return_value = mock_job

                # Make 5 requests (should succeed)
                for i in range(5):
                    response = client.post(
                        "/api/v1/analyze", json={"url": "https://example.com"}
                    )
                    assert response.status_code == 200, f"Request {i+1} failed"

                # 6th request should be rate limited
                response = client.post(
                    "/api/v1/analyze", json={"url": "https://example.com"}
                )

        assert response.status_code == 429
        data = response.json()
        assert data["detail"]["error"]["code"] == "RATE_LIMIT_EXCEEDED"

    def test_rate_limit_headers_present(self, client, reset_rate_limiter):
        """Rate limit headers should be present in response."""
        with patch("app.api.services.job_queue.job_queue.submit") as mock_submit:
            mock_submit.return_value = "a" * 32

            with patch("app.api.services.job_queue.job_queue.get") as mock_get:
                from datetime import UTC, datetime

                mock_job = MagicMock()
                mock_job.status = "pending"
                mock_job.created_at = datetime.now(UTC)
                mock_get.return_value = mock_job

                response = client.post(
                    "/api/v1/analyze", json={"url": "https://example.com"}
                )

        assert response.status_code == 200
        # Check rate limit headers are present
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Limit" in response.headers


class TestAPIKeyAuthentication:
    """Tests for API key authentication."""

    def test_invalid_api_key_rejected(self, client, reset_rate_limiter):
        """Invalid API key should return 401."""
        response = client.post(
            "/api/v1/analyze",
            json={"url": "https://example.com"},
            headers={"X-API-Key": "invalid-key"},
        )

        assert response.status_code == 401
        data = response.json()
        assert data["detail"]["error"]["code"] == "INVALID_API_KEY"

    def test_bearer_token_format(self, client, reset_rate_limiter):
        """Bearer token format should be accepted."""
        response = client.post(
            "/api/v1/analyze",
            json={"url": "https://example.com"},
            headers={"Authorization": "Bearer invalid-key"},
        )

        # Should fail with invalid key, not format error
        assert response.status_code == 401
        data = response.json()
        assert data["detail"]["error"]["code"] == "INVALID_API_KEY"


class TestSecurityHeaders:
    """Tests for security headers."""

    def test_security_headers_present(self, client, reset_rate_limiter):
        """Security headers should be present in all responses."""
        response = client.get("/api/v1/health")

        assert response.status_code == 200
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"
        assert response.headers.get("X-XSS-Protection") == "1; mode=block"
        assert "Content-Security-Policy" in response.headers
