"""Configuration management for ig2rss.

This module handles loading configuration from environment variables
and provides default values where appropriate.
"""

import os
from typing import Optional


class Config:
    """Application configuration loaded from environment variables."""

    # Instagram credentials (required)
    INSTAGRAM_USERNAME: str = os.getenv("INSTAGRAM_USERNAME", "")
    INSTAGRAM_PASSWORD: str = os.getenv("INSTAGRAM_PASSWORD", "")
    
    # Two-Factor Authentication (optional)
    INSTAGRAM_2FA_SEED: Optional[str] = os.getenv("INSTAGRAM_2FA_SEED", None)

    # Polling configuration
    POLL_INTERVAL: int = int(os.getenv("POLL_INTERVAL", "600"))  # seconds (10 min)
    FETCH_COUNT: int = int(os.getenv("FETCH_COUNT", "20"))  # posts per poll

    # RSS feed configuration
    RSS_FEED_LIMIT: int = int(os.getenv("RSS_FEED_LIMIT", "50"))
    RSS_FEED_DAYS: int = int(os.getenv("RSS_FEED_DAYS", "30"))

    # Storage paths
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "/data/ig2rss.db")
    MEDIA_CACHE_PATH: str = os.getenv("MEDIA_CACHE_PATH", "/data/media")
    SESSION_FILE: str = os.getenv("SESSION_FILE", "/data/instagram_session.json")

    # HTTP server
    BASE_URL: str = os.getenv("BASE_URL", "http://localhost:8080")
    PORT: int = int(os.getenv("PORT", "8080"))
    HOST: str = os.getenv("HOST", "0.0.0.0")

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    @classmethod
    def validate(cls) -> list[str]:
        """Validate required configuration.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        if not cls.INSTAGRAM_USERNAME:
            errors.append("INSTAGRAM_USERNAME environment variable is required")

        if not cls.INSTAGRAM_PASSWORD:
            errors.append("INSTAGRAM_PASSWORD environment variable is required")
        
        # Validate TOTP seed format if provided
        if cls.INSTAGRAM_2FA_SEED:
            import re
            # Remove whitespace for validation
            seed_clean = re.sub(r'\s+', '', cls.INSTAGRAM_2FA_SEED)
            # Base32 alphabet is A-Z and 2-7, also allow hex (0-9, a-f, A-F)
            # We support both formats now
            if not re.match(r'^[A-Z2-7\-_]+$', seed_clean.upper()) and \
               not re.match(r'^[0-9a-fA-F]+$', seed_clean):
                errors.append(
                    "INSTAGRAM_2FA_SEED must be either base32 (A-Z and 2-7) or hex-encoded (0-9, A-F). "
                    "Spaces, tabs, hyphens and underscores will be automatically removed."
                )

        if cls.POLL_INTERVAL < 60:
            errors.append("POLL_INTERVAL must be at least 60 seconds")

        if cls.FETCH_COUNT < 1 or cls.FETCH_COUNT > 50:
            errors.append("FETCH_COUNT must be between 1 and 50")

        if cls.RSS_FEED_LIMIT < 1:
            errors.append("RSS_FEED_LIMIT must be at least 1")

        if cls.RSS_FEED_DAYS < 1:
            errors.append("RSS_FEED_DAYS must be at least 1")

        return errors

    @classmethod
    def is_valid(cls) -> bool:
        """Check if configuration is valid.

        Returns:
            True if configuration is valid, False otherwise
        """
        return len(cls.validate()) == 0
