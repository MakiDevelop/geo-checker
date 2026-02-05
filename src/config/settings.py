"""Centralized configuration settings."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class FetcherSettings:
    """Settings for HTML fetcher."""
    request_timeout: int = 15
    max_response_size: int = 10 * 1024 * 1024  # 10 MB
    max_redirects: int = 5
    user_agent: str = "GEO-Checker/2.0 (+https://gc.ranran.tw)"


@dataclass
class PlaywrightSettings:
    """Settings for Playwright JS rendering."""
    max_concurrent_browsers: int = 2
    js_render_timeout: int = 30000  # ms
    semaphore_timeout: int = 60  # seconds


@dataclass
class NLPSettings:
    """Settings for NLP processing."""
    # spaCy model preference order
    # Will try each model in order until one loads successfully
    spacy_models: list[str] = field(default_factory=lambda: [
        "en_core_web_sm",  # English (default, fast)
        "xx_ent_wiki_sm",  # Multilingual entities
    ])
    # Entity labels to extract
    entity_labels: tuple[str, ...] = ("PERSON", "ORG", "GPE", "DATE", "NORP", "FAC", "LOC", "EVENT")
    # Enable CJK-specific processing
    enable_cjk_fallback: bool = True


@dataclass
class GeoScoringSettings:
    """Settings for GEO scoring thresholds."""
    # Accessibility score (max 40)
    crawler_block_penalty: int = 10  # per blocked crawler
    noindex_penalty: int = 15
    nofollow_penalty: int = 5
    blocker_penalty: int = 5  # per blocker

    # Structure score thresholds
    heading_excellent_threshold: int = 5
    heading_good_threshold: int = 3
    list_excellent_threshold: int = 2
    table_bonus_threshold: int = 1

    # Quality score thresholds
    flesch_excellent_threshold: int = 60
    flesch_good_threshold: int = 50
    flesch_fair_threshold: int = 40
    flesch_poor_threshold: int = 30
    definition_excellent_threshold: int = 3
    definition_good_threshold: int = 2
    content_ratio_excellent_threshold: float = 0.7
    content_ratio_good_threshold: float = 0.5
    quotable_excellent_threshold: int = 3

    # Grade thresholds
    grade_a_threshold: int = 90
    grade_b_threshold: int = 75
    grade_c_threshold: int = 60
    grade_d_threshold: int = 40


@dataclass
class SeoSettings:
    """Settings for SEO checker thresholds."""
    title_min_length: int = 30
    title_max_length: int = 60
    title_optimal_min: int = 50
    title_optimal_max: int = 60

    description_min_length: int = 70
    description_max_length: int = 160
    description_optimal_min: int = 120
    description_optimal_max: int = 160

    min_content_words: int = 300  # Thin content threshold


@dataclass
class SecuritySettings:
    """Security-related settings."""
    csrf_token_expiry: int = 3600  # 1 hour
    rate_limit_requests: int = 10
    rate_limit_window: int = 60  # seconds


@dataclass
class APISettings:
    """API-specific settings."""
    # Rate limiting (requests per minute)
    anonymous_rate_limit: int = 5
    authenticated_rate_limit: int = 30
    rate_limit_window: int = 60  # seconds

    # Job queue
    job_max_workers: int = 3
    job_retention_hours: int = 24  # Clean up old jobs after this

    # CORS
    cors_origins: list[str] = field(default_factory=lambda: ["*"])


@dataclass
class GhostSettings:
    """Settings for Ghost Admin API integration."""
    url: str = ""  # e.g. "https://marketing.91app.com"
    admin_api_key: str = ""  # format: "id:secret"


@dataclass
class Settings:
    """Main application settings container."""
    fetcher: FetcherSettings = field(default_factory=FetcherSettings)
    playwright: PlaywrightSettings = field(default_factory=PlaywrightSettings)
    nlp: NLPSettings = field(default_factory=NLPSettings)
    geo_scoring: GeoScoringSettings = field(default_factory=GeoScoringSettings)
    seo: SeoSettings = field(default_factory=SeoSettings)
    security: SecuritySettings = field(default_factory=SecuritySettings)
    api: APISettings = field(default_factory=APISettings)
    ghost: GhostSettings = field(default_factory=GhostSettings)

    # Application settings
    debug: bool = False
    secret_key: str = "geo-checker-dev-key-change-in-production"

    def __post_init__(self):
        """Load settings from environment variables."""
        # Override with environment variables if present
        self.debug = os.environ.get("GEO_CHECKER_DEBUG", "").lower() in ("true", "1", "yes")
        self.secret_key = os.environ.get("GEO_CHECKER_SECRET_KEY", self.secret_key)

        # Fetcher overrides
        if timeout := os.environ.get("GEO_CHECKER_REQUEST_TIMEOUT"):
            self.fetcher.request_timeout = int(timeout)

        # Playwright overrides
        if max_browsers := os.environ.get("GEO_CHECKER_MAX_BROWSERS"):
            self.playwright.max_concurrent_browsers = int(max_browsers)

        # Rate limiting overrides
        if rate_limit := os.environ.get("GEO_CHECKER_RATE_LIMIT"):
            self.security.rate_limit_requests = int(rate_limit)

        # API overrides
        if api_anon_limit := os.environ.get("GEO_API_ANONYMOUS_RATE_LIMIT"):
            self.api.anonymous_rate_limit = int(api_anon_limit)
        if api_auth_limit := os.environ.get("GEO_API_AUTHENTICATED_RATE_LIMIT"):
            self.api.authenticated_rate_limit = int(api_auth_limit)
        if job_workers := os.environ.get("GEO_API_JOB_WORKERS"):
            self.api.job_max_workers = int(job_workers)
        if cors := os.environ.get("GEO_API_CORS_ORIGINS"):
            self.api.cors_origins = [o.strip() for o in cors.split(",")]

        # Ghost Admin API
        if ghost_url := os.environ.get("GHOST_URL"):
            self.ghost.url = ghost_url.rstrip("/")
        if ghost_key := os.environ.get("GHOST_ADMIN_API_KEY"):
            self.ghost.admin_api_key = ghost_key


# Global settings instance
settings = Settings()
