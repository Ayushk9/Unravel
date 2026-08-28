"""Environment-backed application settings."""

from functools import lru_cache
from pathlib import Path
from uuid import UUID

from pydantic_settings import BaseSettings, SettingsConfigDict


API_DIRECTORY = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables and ``.env``."""

    database_url: str | None = None
    supabase_jwt_secret: str | None = None
    supabase_jwt_audience: str = "authenticated"
    gemini_api_key: str | None = None
    environment: str = "local"
    # Development only. These defaults deliberately match apps/web's stub.
    dev_stub_token: str = "mock-household-token"
    dev_stub_household_id: UUID = UUID("01a043f0-7194-7a1a-8df8-e496869dab10")
    upload_directory: Path = API_DIRECTORY / "data" / "uploads"

    model_config = SettingsConfigDict(
        env_file=API_DIRECTORY / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return one settings instance for the running process."""
    return Settings()
