from __future__ import annotations

from app.core.config import Settings


def _settings(**overrides: str) -> Settings:
    values = dict(
        database_url="postgresql+asyncpg://u:p@localhost/x",
        supabase_url="https://x.supabase.co",
        supabase_service_role_key="k",
        gemini_api_key="k",
        environment="prod",
        # Set explicitly: conftest.py puts a value in the environment for other tests.
        cors_allowed_origins="",
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_dev_always_allows_the_vite_dev_server() -> None:
    assert _settings(environment="dev").cors_origin_list == ["http://localhost:5173"]


def test_deployed_origins_come_from_the_environment() -> None:
    settings = _settings(cors_allowed_origins="https://app.example.com, https://staging.example.com ,")

    assert settings.cors_origin_list == ["https://app.example.com", "https://staging.example.com"]


def test_prod_does_not_allow_the_dev_server_unless_listed() -> None:
    assert _settings(environment="prod").cors_origin_list == []


def test_a_wildcard_origin_is_never_allowed() -> None:
    assert _settings(cors_allowed_origins="*, https://app.example.com").cors_origin_list == ["https://app.example.com"]


def test_parse_limits_have_safe_defaults() -> None:
    settings = _settings()

    assert settings.parse_timeout_seconds == 300
    assert settings.max_concurrent_parses == 1
    assert settings.storage_bucket == "documents"
