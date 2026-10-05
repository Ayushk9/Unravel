"""Application settings, read from environment variables and apps/api/.env.

The first four fields are required and have no default. If one is missing
the process fails at startup with a message naming the variable, instead of
starting and failing later on the first request that needs it.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/api/ — two levels up from this file (app/core/config.py).
API_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    database_url: str
    # Project URL. Token verification derives the public-key (JWKS) address from it.
    supabase_url: str
    gemini_api_key: str
    # A fixed set, not a free string: a typo such as "development" must fail
    # at startup rather than silently behave like production (or like dev).
    environment: Literal["dev", "test", "prod"]

    # Browser origins allowed to call the API, comma-separated. Not a secret,
    # so it has a default: the Vite dev server the web app runs on.
    cors_allowed_origins: str = "http://localhost:5173"

    # A real environment variable always wins over the same name in .env.
    model_config = SettingsConfigDict(
        env_file=API_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Read the settings once per process."""
    return Settings()
