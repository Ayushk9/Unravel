"""Application settings, read from environment variables and apps/api/.env.

Settings without a default are required. If one is missing the process
fails at startup with a message naming the variable, instead of starting
and failing later on the first request that needs it.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/api/ — two levels up from this file (app/core/config.py).
API_DIR = Path(__file__).resolve().parents[2]

# The Vite dev server the web app runs on during development.
DEV_WEB_ORIGIN = "http://localhost:5173"


class Settings(BaseSettings):
    database_url: str
    # Project URL. Token verification derives the public-key (JWKS) address
    # from it, and the Storage API lives under it.
    supabase_url: str
    gemini_api_key: str
    # A fixed set, not a free string: a typo such as "development" must fail
    # at startup rather than silently behave like production (or like dev).
    environment: Literal["dev", "test", "prod"]

    # Network address the server listens on when started with `python -m app`.
    # 0.0.0.0 means "every network interface", so a phone on the same Wi-Fi
    # can reach it. 127.0.0.1 would accept connections from this Mac only.
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)

    # Where uploaded files are kept. "local" is a folder on this machine
    # (the default: the demo runs on one Mac). "supabase" is a private
    # Supabase Storage bucket.
    storage_backend: Literal["local", "supabase"] = "local"
    # Folder for the local backend. A relative path is taken from apps/api.
    local_storage_dir: str = "storage"
    # Needed only for the supabase backend. Server-side only: this key
    # bypasses every access rule in the project.
    supabase_service_role_key: str | None = None
    storage_bucket: str = "documents"

    # A parse still running after this many seconds is terminated.
    parse_timeout_seconds: float = Field(default=300, gt=0)
    # Labelling a claim document is one quick model call; it should never take long.
    classify_timeout_seconds: float = Field(default=60, gt=0)
    # Docling is memory-heavy: two parses at once can exhaust a small host.
    max_concurrent_parses: int = Field(default=1, ge=1)

    # Deployed web origins, comma-separated. Never "*".
    cors_allowed_origins: str = ""

    # A real environment variable always wins over the same name in .env.
    model_config = SettingsConfigDict(
        env_file=API_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def _supabase_backend_needs_its_key(self) -> Settings:
        if self.storage_backend == "supabase" and not self.supabase_service_role_key:
            raise ValueError("SUPABASE_SERVICE_ROLE_KEY is required when STORAGE_BACKEND=supabase")
        return self

    @property
    def local_storage_path(self) -> Path:
        path = Path(self.local_storage_dir).expanduser()
        return path if path.is_absolute() else API_DIR / path

    @property
    def cors_origin_list(self) -> list[str]:
        """Exact origins allowed to call the API from a browser.

        The dev server is allowed only in dev. A "*" entry is dropped: the
        list must name origins explicitly.
        """
        origins = [origin.strip() for origin in self.cors_allowed_origins.split(",")]
        origins = [origin for origin in origins if origin and origin != "*"]
        if self.environment == "dev" and DEV_WEB_ORIGIN not in origins:
            origins.append(DEV_WEB_ORIGIN)
        return origins


@lru_cache
def get_settings() -> Settings:
    """Read the settings once per process."""
    return Settings()
