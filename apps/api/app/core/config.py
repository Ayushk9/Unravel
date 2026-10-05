"""Application settings, read from environment variables and apps/api/.env.

Every field is required and has no default. If one is missing the process
fails at startup with a message naming the variable, instead of starting
and failing later on the first request that needs it.
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
    supabase_jwt_secret: str
    gemini_api_key: str
    # A fixed set, not a free string: a typo such as "development" must fail
    # at startup rather than silently behave like production (or like dev).
    environment: Literal["dev", "test", "prod"]

    # A real environment variable always wins over the same name in .env.
    model_config = SettingsConfigDict(
        env_file=API_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Read the settings once per process."""
    return Settings()
