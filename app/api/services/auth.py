"""API Key authentication."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass


@dataclass
class APIKeyInfo:
    """Information about an API key."""

    name: str
    tier: str
    rate_limit: int


class APIKeyManager:
    """Manage API keys loaded from environment variables.

    Keys are defined as environment variables:
        GEO_API_KEY_<name>=<key>
        GEO_API_KEY_<name>=<key>:<tier>

    Where tier can be: free, standard, premium
    Default tier is 'standard'.

    Examples:
        GEO_API_KEY_CLIENT1=abc123xyz
        GEO_API_KEY_PREMIUM_USER=def456:premium
    """

    TIER_LIMITS = {
        "free": 10,
        "standard": 30,
        "premium": 100,
    }

    def __init__(self):
        self._keys: dict[str, APIKeyInfo] = {}
        self._load_keys()

    def _load_keys(self) -> None:
        """Load API keys from environment variables."""
        for key, value in os.environ.items():
            if not key.startswith("GEO_API_KEY_"):
                continue

            name = key[12:]  # Remove "GEO_API_KEY_" prefix
            if not name or not value:
                continue

            # Parse value: <api_key> or <api_key>:<tier>
            parts = value.split(":", 1)
            api_key = parts[0]
            tier = parts[1] if len(parts) > 1 else "standard"

            if tier not in self.TIER_LIMITS:
                tier = "standard"

            # Store hashed key for security
            key_hash = self._hash_key(api_key)
            self._keys[key_hash] = APIKeyInfo(
                name=name,
                tier=tier,
                rate_limit=self.TIER_LIMITS[tier],
            )

    @staticmethod
    def _hash_key(api_key: str) -> str:
        """Hash an API key for secure storage/comparison."""
        return hashlib.sha256(api_key.encode()).hexdigest()

    def validate(self, api_key: str) -> APIKeyInfo | None:
        """Validate an API key and return its info if valid."""
        if not api_key:
            return None
        key_hash = self._hash_key(api_key)
        return self._keys.get(key_hash)

    def get_rate_limit(self, api_key: str | None) -> int:
        """Get rate limit for the given key (or anonymous default)."""
        from src.config.settings import settings

        if not api_key:
            return settings.api.anonymous_rate_limit

        info = self.validate(api_key)
        if info:
            return info.rate_limit

        # Invalid key gets anonymous rate limit
        return settings.api.anonymous_rate_limit

    def reload(self) -> None:
        """Reload keys from environment (for testing/hot reload)."""
        self._keys.clear()
        self._load_keys()


# Global instance
api_key_manager = APIKeyManager()
