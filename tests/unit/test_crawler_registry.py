"""Registry tests for the 26-crawler catalog (v4.1.1 additions)."""
from __future__ import annotations

from src.fetcher.html_fetcher import FetchResult
from src.geo.geo_checker import (
    _AGENT_MAP,
    _CORE_CRAWLERS,
    _ai_crawler_access,
    _score_accessibility,
)
from src.toolkit.robots_generator import generate_robots_txt

_NEW_KEYS = (
    "google-cloudvertexbot",
    "meta-externalfetcher",
    "bingbot",
)


class TestCrawlerRegistry:
    def test_catalog_has_v411_uas(self) -> None:
        for key in _NEW_KEYS:
            assert key in _AGENT_MAP, f"missing {key}"
        assert len(_AGENT_MAP) == 26

    def test_new_uas_are_extended_not_core(self) -> None:
        for key in _NEW_KEYS:
            assert key not in _CORE_CRAWLERS

    def test_categories(self) -> None:
        assert _AGENT_MAP["google-cloudvertexbot"]["category"] == "search"
        assert _AGENT_MAP["bingbot"]["category"] == "search"
        assert _AGENT_MAP["meta-externalfetcher"]["category"] == "user-triggered"

    def test_robots_txt_names_new_uas(self) -> None:
        text = generate_robots_txt({}, url="https://example.com/")
        assert "User-agent: Google-CloudVertexBot" in text
        assert "User-agent: Bingbot" in text
        assert "User-agent: Meta-ExternalFetcher" in text

    def test_robots_txt_allows_new_search_and_user_bots(self) -> None:
        text = generate_robots_txt({}, url="https://example.com/")
        # Each new UA is followed by Allow, not Disallow (they are not training).
        for ua in (
            "Google-CloudVertexBot",
            "Bingbot",
            "Meta-ExternalFetcher",
        ):
            idx = text.index(f"User-agent: {ua}")
            snippet = text[idx : idx + 80]
            assert "Allow: /" in snippet
            assert "Disallow: /" not in snippet

    def test_parse_disallow_for_new_uas(self) -> None:
        robots = (
            "User-agent: Bingbot\nDisallow: /\n\n"
            "User-agent: Google-CloudVertexBot\nDisallow: /\n\n"
            "User-agent: Meta-ExternalFetcher\nDisallow: /\n\n"
            "User-agent: *\nAllow: /\n"
        )
        fetch_result = FetchResult(
            html="<html></html>",
            robots_txt=robots,
            robots_txt_found=True,
            final_url="https://example.com/page",
        )
        result = _ai_crawler_access(
            "https://example.com/page",
            "<html></html>",
            fetch_result=fetch_result,
        )
        crawlers = result["crawlers"]
        assert crawlers["bingbot"]["status"] == "disallow"
        assert crawlers["google_cloudvertexbot"]["status"] == "disallow"
        assert crawlers["meta_externalfetcher"]["status"] == "disallow"
        assert crawlers["gptbot"]["status"] == "allow"

    def test_blocking_extended_is_cheaper_than_core(self) -> None:
        base = {
            "crawlers": {
                "gptbot": {"status": "allow", "display": "GPTBot"},
            },
            "meta_robots": {"noindex": False, "nofollow": False},
            "x_robots_tag": {"noindex": False, "nofollow": False},
        }
        blocked_core = {
            **base,
            "crawlers": {
                "gptbot": {"status": "disallow", "display": "GPTBot"},
            },
        }
        blocked_bing = {
            **base,
            "crawlers": {
                "gptbot": {"status": "allow", "display": "GPTBot"},
                "bingbot": {"status": "disallow", "display": "Bingbot"},
            },
        }
        score_core = _score_accessibility(blocked_core, [])
        score_bing = _score_accessibility(blocked_bing, [])
        score_ok = _score_accessibility(base, [])
        assert score_ok - score_core == 5
        assert score_ok - score_bing == 1
