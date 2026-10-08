"""Local-disk storage and the route that serves its signed links. No database needed."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.storage.base import StorageError, build_object_path
from app.storage.factory import create_storage
from app.storage.local import LOCAL_FILES_ROUTE, LocalDiskStorage
from app.storage.supabase import SupabaseStorage

HOUSEHOLD = UUID("01920000-0000-7000-8000-000000000001")
DOCUMENT = UUID("01920000-0000-7000-8000-0000000000d1")
PDF = b"%PDF-1.7\n" + b"0123456789" * 100
PATH = build_object_path(HOUSEHOLD, DOCUMENT, "My Policy.pdf")


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = dict(
        database_url="postgresql+asyncpg://u:p@localhost/x",
        supabase_url="https://x.supabase.co",
        gemini_api_key="k",
        environment="test",
        cors_allowed_origins="http://localhost:5173",
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def storage(tmp_path: Path) -> LocalDiskStorage:
    return LocalDiskStorage(tmp_path / "storage")


def test_file_is_written_under_household_then_document(storage: LocalDiskStorage, tmp_path: Path) -> None:
    asyncio.run(storage.save(PATH, PDF, "application/pdf"))

    on_disk = tmp_path / "storage" / str(HOUSEHOLD) / str(DOCUMENT) / "My_Policy.pdf"
    assert on_disk.read_bytes() == PDF


def test_saving_twice_to_the_same_path_is_refused(storage: LocalDiskStorage) -> None:
    asyncio.run(storage.save(PATH, PDF, "application/pdf"))

    with pytest.raises(StorageError):
        asyncio.run(storage.save(PATH, b"other", "application/pdf"))


def test_parser_gets_a_temporary_copy_that_is_deleted_and_the_original_stays(storage: LocalDiskStorage, tmp_path: Path) -> None:
    async def scenario() -> Path:
        await storage.save(PATH, PDF, "application/pdf")
        async with storage.open_to_tempfile(PATH) as file_path:
            assert file_path.read_bytes() == PDF
            assert not file_path.is_relative_to(tmp_path / "storage"), "a copy, not the stored original"
            return file_path

    temporary = asyncio.run(scenario())

    assert not temporary.exists()
    assert (tmp_path / "storage" / PATH).read_bytes() == PDF


def test_delete_removes_the_file_and_its_empty_folders(storage: LocalDiskStorage, tmp_path: Path) -> None:
    async def scenario() -> None:
        await storage.save(PATH, PDF, "application/pdf")
        await storage.delete(PATH)
        await storage.delete(PATH)  # deleting again is not an error

    asyncio.run(scenario())

    assert list((tmp_path / "storage").iterdir()) == []


@pytest.mark.parametrize("path", ["../outside.pdf", "a/../../outside.pdf", "/etc/passwd", ""])
def test_paths_outside_the_storage_folder_are_refused(storage: LocalDiskStorage, path: str) -> None:
    with pytest.raises(StorageError):
        asyncio.run(storage.save(path, PDF, "application/pdf"))


def test_missing_file_cannot_be_opened_or_signed(storage: LocalDiskStorage) -> None:
    async def open_missing() -> None:
        async with storage.open_to_tempfile(PATH):
            pass

    with pytest.raises(StorageError):
        asyncio.run(open_missing())
    with pytest.raises(StorageError):
        asyncio.run(storage.signed_url(PATH, 300))


# --- signed links ---


def _signed_parts(storage: LocalDiskStorage, expires_in: int = 300) -> dict[str, str]:
    asyncio.run(storage.save(PATH, PDF, "application/pdf"))
    url = asyncio.run(storage.signed_url(PATH, expires_in))
    assert url.startswith(f"{LOCAL_FILES_ROUTE}?")
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}


def test_a_signed_link_opens_its_file(storage: LocalDiskStorage) -> None:
    parts = _signed_parts(storage)

    assert storage.open_signed(parts["path"], int(parts["expires"]), parts["signature"]).read_bytes() == PDF


def test_changing_the_path_or_the_expiry_breaks_the_signature(storage: LocalDiskStorage) -> None:
    parts = _signed_parts(storage)
    other_path = build_object_path(HOUSEHOLD, UUID(int=5), "someone-elses.pdf")
    asyncio.run(storage.save(other_path, b"%PDF-private", "application/pdf"))

    with pytest.raises(StorageError):
        storage.open_signed(other_path, int(parts["expires"]), parts["signature"])
    with pytest.raises(StorageError):
        storage.open_signed(parts["path"], int(parts["expires"]) + 3600, parts["signature"])
    with pytest.raises(StorageError):
        storage.open_signed(parts["path"], int(parts["expires"]), "0" * 64)


def test_an_expired_link_is_refused(storage: LocalDiskStorage) -> None:
    parts = _signed_parts(storage, expires_in=-1)

    with pytest.raises(StorageError, match="expired"):
        storage.open_signed(parts["path"], int(parts["expires"]), parts["signature"])


def test_links_from_one_server_run_do_not_work_on_another(tmp_path: Path) -> None:
    """The signing key is made fresh at startup, so a restart invalidates old links."""
    first = LocalDiskStorage(tmp_path / "storage")
    parts = _signed_parts(first)
    after_restart = LocalDiskStorage(tmp_path / "storage")

    with pytest.raises(StorageError):
        after_restart.open_signed(parts["path"], int(parts["expires"]), parts["signature"])


# --- the route that serves signed links ---


@pytest.fixture
def served(tmp_path: Path) -> tuple[TestClient, str]:
    app = create_app(_settings(local_storage_dir=str(tmp_path / "storage")))
    storage = app.state.storage
    assert isinstance(storage, LocalDiskStorage)
    asyncio.run(storage.save(PATH, PDF, "application/pdf"))
    return TestClient(app, raise_server_exceptions=False), asyncio.run(storage.signed_url(PATH, 300))


def test_signed_link_serves_the_file_without_a_token(served: tuple[TestClient, str]) -> None:
    client, url = served

    response = client.get(url)  # no Authorization header

    assert response.status_code == 200
    assert response.content == PDF
    assert response.headers["content-type"] == "application/pdf"


def test_signed_link_supports_range_requests_for_the_pdf_viewer(served: tuple[TestClient, str]) -> None:
    client, url = served

    response = client.get(url, headers={"Range": "bytes=0-8", "Origin": "http://localhost:5173"})

    assert response.status_code == 206
    assert response.content == PDF[:9]
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "content-range" in response.headers["access-control-expose-headers"].lower()


@pytest.mark.parametrize("tamper", ["signature", "path", "expires"])
def test_a_tampered_link_is_403_with_the_envelope(served: tuple[TestClient, str], tamper: str) -> None:
    client, url = served
    parts = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
    parts[tamper] = {"signature": "f" * 64, "path": "../../../etc/passwd", "expires": str(int(time.time()) + 99999)}[tamper]

    response = client.get(LOCAL_FILES_ROUTE, params=parts)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "link_not_valid"
    assert set(response.json()["error"]) == {"code", "message", "field_errors", "request_id", "retryable"}


def test_link_without_its_parameters_is_422(served: tuple[TestClient, str]) -> None:
    client, _ = served

    assert client.get(LOCAL_FILES_ROUTE).status_code == 422


# --- choosing the backend ---


def test_local_disk_is_the_default_backend_and_needs_no_supabase_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # conftest.py sets these for other tests; remove them to see the real defaults.
    monkeypatch.delenv("STORAGE_BACKEND")
    monkeypatch.delenv("LOCAL_STORAGE_DIR")
    settings = _settings()

    assert settings.storage_backend == "local"
    assert settings.supabase_service_role_key is None
    assert settings.local_storage_path.name == "storage" and settings.local_storage_path.parent.name == "api"
    assert isinstance(create_storage(settings), LocalDiskStorage)


def test_supabase_backend_can_still_be_selected() -> None:
    settings = _settings(storage_backend="supabase", supabase_service_role_key="secret")

    assert isinstance(create_storage(settings), SupabaseStorage)


def test_supabase_backend_without_its_key_fails_at_startup() -> None:
    with pytest.raises(ValueError, match="SUPABASE_SERVICE_ROLE_KEY is required"):
        _settings(storage_backend="supabase")


def test_server_listens_on_all_interfaces_by_default() -> None:
    settings = _settings()

    assert (settings.host, settings.port) == ("0.0.0.0", 8000)
    assert _settings(host="127.0.0.1", port=9000).host == "127.0.0.1"
