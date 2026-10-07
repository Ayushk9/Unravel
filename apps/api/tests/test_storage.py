"""Storage: path rules, the temporary-file guarantee, and the Supabase REST calls."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from app.storage.base import (
    TEMP_DIRECTORY_PREFIX,
    StorageError,
    build_object_path,
    remove_stale_temporary_files,
    sanitise_filename,
)
from app.storage.memory import InMemoryStorage
from app.storage.supabase import SupabaseStorage

HOUSEHOLD = UUID("01920000-0000-7000-8000-000000000001")
DOCUMENT = UUID("01920000-0000-7000-8000-0000000000d1")


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("policy.pdf", "policy.pdf"),
        ("My Policy (final) 2026.pdf", "My_Policy_final_2026.pdf"),
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\a\\policy.pdf", "policy.pdf"),
        ("पॉलिसी.pdf", "pdf"),
        ("", "document"),
        ("...", "document"),
        ("a/b/c.pdf", "c.pdf"),
    ],
)
def test_filenames_are_reduced_to_safe_characters(given: str, expected: str) -> None:
    assert sanitise_filename(given) == expected


def test_long_filenames_are_shortened_but_keep_their_extension() -> None:
    cleaned = sanitise_filename("x" * 500 + ".pdf")

    assert len(cleaned) <= 100
    assert cleaned.endswith(".pdf")


def test_object_path_is_household_then_document_then_filename() -> None:
    path = build_object_path(HOUSEHOLD, DOCUMENT, "../My Policy.pdf")

    assert path == f"{HOUSEHOLD}/{DOCUMENT}/My_Policy.pdf"
    assert ".." not in path


def test_temporary_file_exists_inside_the_block_and_is_deleted_after() -> None:
    storage = InMemoryStorage()

    async def scenario() -> Path:
        await storage.save("h/d/policy.pdf", b"%PDF-bytes", "application/pdf")
        async with storage.open_to_tempfile("h/d/policy.pdf") as file_path:
            assert file_path.read_bytes() == b"%PDF-bytes"
            return file_path

    file_path = asyncio.run(scenario())

    assert not file_path.exists()
    assert not file_path.parent.exists()


def test_temporary_file_is_deleted_when_the_block_raises() -> None:
    storage = InMemoryStorage()
    seen: list[Path] = []

    async def scenario() -> None:
        await storage.save("h/d/policy.pdf", b"%PDF-bytes", "application/pdf")
        async with storage.open_to_tempfile("h/d/policy.pdf") as file_path:
            seen.append(file_path)
            raise RuntimeError("the parse blew up")

    with pytest.raises(RuntimeError):
        asyncio.run(scenario())

    assert seen and not seen[0].exists()


def test_leftover_temporary_directories_are_removed_at_startup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """What a server killed with SIGKILL leaves behind is swept up on the next start."""
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    stale = tmp_path / f"{TEMP_DIRECTORY_PREFIX}abc123"
    stale.mkdir()
    (stale / "policy.pdf").write_bytes(b"%PDF-left-behind")
    unrelated = tmp_path / "someone-elses-file"
    unrelated.write_text("keep me")

    removed = remove_stale_temporary_files()

    assert removed == 1
    assert not stale.exists()
    assert unrelated.exists(), "only this app's own temporary directories are touched"


def test_memory_storage_refuses_to_overwrite_and_tolerates_double_delete() -> None:
    storage = InMemoryStorage()

    async def scenario() -> None:
        await storage.save("p", b"1", "application/pdf")
        with pytest.raises(StorageError):
            await storage.save("p", b"2", "application/pdf")
        await storage.delete("p")
        await storage.delete("p")

    asyncio.run(scenario())
    assert storage.objects == {}


# --- SupabaseStorage, against a fake HTTP transport (no network) ---


def _supabase(handler) -> SupabaseStorage:
    return SupabaseStorage(
        "https://proj.supabase.co/", "secret-key", "documents", transport=httpx.MockTransport(handler)
    )


def test_supabase_save_posts_bytes_with_the_key_and_no_overwrite() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"Key": "documents/h/d/policy.pdf"})

    asyncio.run(_supabase(handler).save("h/d/policy.pdf", b"%PDF-bytes", "application/pdf"))

    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://proj.supabase.co/storage/v1/object/documents/h/d/policy.pdf"
    assert request.headers["authorization"] == "Bearer secret-key"
    assert request.headers["apikey"] == "secret-key"
    assert request.headers["x-upsert"] == "false"
    assert request.headers["content-type"] == "application/pdf"
    assert request.content == b"%PDF-bytes"


def test_supabase_signed_url_is_absolute_and_asks_for_the_given_lifetime() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/storage/v1/object/sign/documents/h/d/policy.pdf"
        assert json.loads(request.content) == {"expiresIn": 300}
        return httpx.Response(200, json={"signedURL": "/object/sign/documents/h/d/policy.pdf?token=abc"})

    url = asyncio.run(_supabase(handler).signed_url("h/d/policy.pdf", 300))

    assert url == "https://proj.supabase.co/storage/v1/object/sign/documents/h/d/policy.pdf?token=abc"


def test_supabase_download_writes_a_temporary_file() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF-downloaded")

    async def scenario() -> Path:
        async with _supabase(handler).open_to_tempfile("h/d/policy.pdf") as file_path:
            assert file_path.read_bytes() == b"%PDF-downloaded"
            return file_path

    assert not asyncio.run(scenario()).exists()


def test_supabase_failures_become_storage_errors_without_the_key() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "forbidden"})

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    for handler in (refuse, unreachable):
        with pytest.raises(StorageError) as raised:
            asyncio.run(_supabase(handler).save("h/d/policy.pdf", b"x", "application/pdf"))
        assert "secret-key" not in str(raised.value)


def test_supabase_delete_of_a_missing_object_is_not_an_error() -> None:
    asyncio.run(_supabase(lambda request: httpx.Response(404)).delete("h/d/gone.pdf"))


def test_ensure_bucket_refuses_a_public_bucket() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "documents", "public": True})

    with pytest.raises(StorageError, match="PUBLIC"):
        asyncio.run(_supabase(handler).ensure_bucket())
