"""Ghost Admin API fetcher for draft post analysis."""
from __future__ import annotations

import json
import time
from urllib.parse import urlparse

import jwt
import requests

from src.config.settings import settings


class GhostAPIError(Exception):
    """Raised when Ghost API call fails."""


def is_ghost_url(url: str) -> bool:
    """Check if a URL belongs to a configured Ghost instance."""
    ghost_url = settings.ghost.url
    if not ghost_url:
        return False
    parsed_input = urlparse(url)
    parsed_ghost = urlparse(ghost_url)
    return parsed_input.netloc == parsed_ghost.netloc


def fetch_ghost_post(url: str) -> str:
    """
    Fetch a Ghost post via Admin API and return a synthetic full HTML document.

    Args:
        url: The Ghost post URL

    Returns:
        Full HTML document string

    Raises:
        GhostAPIError: If the API call fails or post is not found
    """
    ghost_url = settings.ghost.url
    api_key = settings.ghost.admin_api_key

    if not ghost_url or not api_key:
        raise GhostAPIError("Ghost API 未設定（需要 GHOST_URL 和 GHOST_ADMIN_API_KEY）")

    slug = _extract_slug_from_url(url)
    token = _create_ghost_jwt(api_key)

    api_endpoint = f"{ghost_url}/ghost/api/admin/posts/slug/{slug}/"

    response = requests.get(
        api_endpoint,
        params={"formats": "html"},
        headers={
            "Authorization": f"Ghost {token}",
            "Content-Type": "application/json",
        },
        timeout=settings.fetcher.request_timeout,
    )

    if response.status_code == 404:
        raise GhostAPIError(f"Ghost 文章不存在：{slug}")
    if response.status_code == 401:
        raise GhostAPIError("Ghost API 驗證失敗，請確認 Admin API Key 是否正確")
    if response.status_code != 200:
        raise GhostAPIError(f"Ghost API 錯誤：HTTP {response.status_code}")

    data = response.json()
    posts = data.get("posts", [])
    if not posts:
        raise GhostAPIError(f"Ghost API 未回傳文章資料：{slug}")

    return _build_html_document(posts[0], url)


def _create_ghost_jwt(api_key: str) -> str:
    """Create a JWT token for Ghost Admin API authentication."""
    try:
        key_id, secret = api_key.split(":")
    except ValueError:
        raise GhostAPIError("Ghost Admin API Key 格式錯誤，應為 'id:secret'")

    iat = int(time.time())
    payload = {
        "iat": iat,
        "exp": iat + 5 * 60,
        "aud": "/admin/",
    }
    header = {
        "alg": "HS256",
        "typ": "JWT",
        "kid": key_id,
    }

    return jwt.encode(
        payload,
        bytes.fromhex(secret),
        algorithm="HS256",
        headers=header,
    )


def _extract_slug_from_url(url: str) -> str:
    """Extract the post slug from a Ghost URL."""
    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.strip("/").split("/") if p]
    if not path_parts:
        raise GhostAPIError(f"無法從 URL 提取 slug：{url}")
    return path_parts[-1]


def _build_html_document(post: dict, original_url: str) -> str:
    """
    Construct a full HTML document from Ghost post fields.

    Maps Ghost API fields to HTML elements that parse_content() expects:
    - title → <title> + <h1>
    - meta_description / custom_excerpt / excerpt → <meta name="description">
    - canonical_url → <link rel="canonical">
    - html → <article> body
    - status=draft → <meta name="robots" content="noindex, nofollow">
    - BlogPosting JSON-LD schema
    """
    title = _escape_html(post.get("title", ""))

    description = (
        post.get("meta_description")
        or post.get("custom_excerpt")
        or post.get("excerpt", "")
    )
    description = _escape_html(description)

    canonical = _escape_html(post.get("canonical_url") or original_url)
    body_html = post.get("html", "")

    status = post.get("status", "draft")
    robots_content = "noindex, nofollow" if status == "draft" else "index, follow"

    # Build Schema.org BlogPosting JSON-LD
    schema = {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": post.get("title", ""),
        "description": post.get("meta_description") or post.get("custom_excerpt") or "",
        "url": post.get("canonical_url") or original_url,
    }
    if published_at := post.get("published_at"):
        schema["datePublished"] = published_at
    if updated_at := post.get("updated_at"):
        schema["dateModified"] = updated_at
    authors = post.get("authors", [])
    if authors and authors[0].get("name"):
        schema["author"] = {"@type": "Person", "name": authors[0]["name"]}

    schema_json = json.dumps(schema, ensure_ascii=False, indent=2)

    og_image = post.get("og_image") or post.get("feature_image", "")
    og_image_tag = f'<meta property="og:image" content="{_escape_html(og_image)}" />' if og_image else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <meta name="description" content="{description}">
    <meta name="robots" content="{robots_content}">
    <link rel="canonical" href="{canonical}">
    <meta property="og:title" content="{title}">
    <meta property="og:description" content="{description}">
    {og_image_tag}
    <script type="application/ld+json">
{schema_json}
    </script>
</head>
<body>
    <article>
        <h1>{title}</h1>
        {body_html}
    </article>
</body>
</html>"""


def _escape_html(text: str) -> str:
    """Escape HTML special characters for safe attribute values."""
    if not text:
        return ""
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )
