"""Unit tests for Ghost Admin API fetcher."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.fetcher.ghost_fetcher import (
    GhostAPIError,
    _build_html_document,
    _create_ghost_jwt,
    _extract_slug_from_url,
    fetch_ghost_post,
    is_ghost_url,
)


class TestExtractSlug:
    def test_simple_slug(self):
        assert _extract_slug_from_url("https://example.com/my-post/") == "my-post"

    def test_no_trailing_slash(self):
        assert _extract_slug_from_url("https://example.com/my-post") == "my-post"

    def test_nested_path(self):
        assert _extract_slug_from_url("https://example.com/blog/my-post/") == "my-post"

    def test_empty_path_raises(self):
        with pytest.raises(GhostAPIError):
            _extract_slug_from_url("https://example.com/")


class TestIsGhostURL:
    @patch("src.fetcher.ghost_fetcher.settings")
    def test_matching_domain(self, mock_settings):
        mock_settings.ghost.url = "https://marketing.91app.com"
        assert is_ghost_url("https://marketing.91app.com/some-post/") is True

    @patch("src.fetcher.ghost_fetcher.settings")
    def test_non_matching_domain(self, mock_settings):
        mock_settings.ghost.url = "https://marketing.91app.com"
        assert is_ghost_url("https://example.com/page") is False

    @patch("src.fetcher.ghost_fetcher.settings")
    def test_no_ghost_configured(self, mock_settings):
        mock_settings.ghost.url = ""
        assert is_ghost_url("https://marketing.91app.com/post/") is False


class TestCreateJWT:
    def test_jwt_has_three_parts(self):
        # 64 hex chars = 32 bytes secret
        api_key = "abc123:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        token = _create_ghost_jwt(api_key)
        assert len(token.split(".")) == 3

    def test_invalid_key_format_raises(self):
        with pytest.raises(GhostAPIError, match="格式錯誤"):
            _create_ghost_jwt("no-colon-here")


class TestBuildHTMLDocument:
    def test_basic_fields(self):
        post = {
            "title": "Test Post",
            "html": "<p>Hello world</p>",
            "meta_description": "A test",
            "status": "draft",
        }
        html = _build_html_document(post, "https://example.com/test/")
        assert "<title>Test Post</title>" in html
        assert "Hello world" in html
        assert 'content="A test"' in html
        assert "noindex" in html

    def test_published_status(self):
        post = {"title": "Pub", "html": "<p>X</p>", "status": "published"}
        html = _build_html_document(post, "https://example.com/pub/")
        assert "index, follow" in html

    def test_fallback_description(self):
        post = {"title": "T", "html": "", "custom_excerpt": "Excerpt here", "status": "draft"}
        html = _build_html_document(post, "https://example.com/t/")
        assert "Excerpt here" in html

    def test_html_escaping_in_title(self):
        post = {"title": 'A "B" & <C>', "html": "", "status": "draft"}
        html = _build_html_document(post, "https://example.com/x/")
        assert "&amp;" in html
        assert "&lt;" in html
        assert "&quot;" in html

    def test_schema_org_present(self):
        post = {"title": "Schema Test", "html": "<p>Body</p>", "status": "draft"}
        html = _build_html_document(post, "https://example.com/s/")
        assert "application/ld+json" in html
        assert "BlogPosting" in html

    def test_canonical_from_post(self):
        post = {
            "title": "T",
            "html": "",
            "status": "draft",
            "canonical_url": "https://custom.com/canonical",
        }
        html = _build_html_document(post, "https://example.com/t/")
        assert "https://custom.com/canonical" in html

    def test_og_image(self):
        post = {
            "title": "T",
            "html": "",
            "status": "draft",
            "feature_image": "https://img.example.com/photo.jpg",
        }
        html = _build_html_document(post, "https://example.com/t/")
        assert "og:image" in html
        assert "photo.jpg" in html


class TestFetchGhostPost:
    @patch("src.fetcher.ghost_fetcher.requests.get")
    @patch("src.fetcher.ghost_fetcher.settings")
    def test_successful_fetch(self, mock_settings, mock_get):
        mock_settings.ghost.url = "https://ghost.example.com"
        mock_settings.ghost.admin_api_key = "abc123:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        mock_settings.fetcher.request_timeout = 15

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "posts": [{
                "title": "Draft Post",
                "html": "<p>Draft content</p>",
                "meta_description": "Draft desc",
                "status": "draft",
            }]
        }
        mock_get.return_value = mock_response

        html = fetch_ghost_post("https://ghost.example.com/draft-post/")
        assert "Draft Post" in html
        assert "Draft content" in html

    @patch("src.fetcher.ghost_fetcher.requests.get")
    @patch("src.fetcher.ghost_fetcher.settings")
    def test_404_raises(self, mock_settings, mock_get):
        mock_settings.ghost.url = "https://ghost.example.com"
        mock_settings.ghost.admin_api_key = "abc123:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        mock_settings.fetcher.request_timeout = 15

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        with pytest.raises(GhostAPIError, match="不存在"):
            fetch_ghost_post("https://ghost.example.com/missing/")

    @patch("src.fetcher.ghost_fetcher.requests.get")
    @patch("src.fetcher.ghost_fetcher.settings")
    def test_401_raises(self, mock_settings, mock_get):
        mock_settings.ghost.url = "https://ghost.example.com"
        mock_settings.ghost.admin_api_key = "abc123:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        mock_settings.fetcher.request_timeout = 15

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_get.return_value = mock_response

        with pytest.raises(GhostAPIError, match="驗證失敗"):
            fetch_ghost_post("https://ghost.example.com/post/")

    @patch("src.fetcher.ghost_fetcher.settings")
    def test_not_configured_raises(self, mock_settings):
        mock_settings.ghost.url = ""
        mock_settings.ghost.admin_api_key = ""

        with pytest.raises(GhostAPIError, match="未設定"):
            fetch_ghost_post("https://ghost.example.com/post/")
