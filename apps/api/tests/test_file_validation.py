"""Upload checks that need no database: they fail before anything is stored."""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.core.auth import CurrentHousehold, get_current_household
from app.main import create_app
from app.services.file_validation import MAX_UPLOAD_BYTES, detect_content_type, sha256_hex
from app.storage.memory import InMemoryStorage

PDF = b"%PDF-1.7\nbody"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def upload_client(storage: InMemoryStorage) -> TestClient:
    app = create_app()
    app.state.storage = storage

    async def household() -> CurrentHousehold:
        return CurrentHousehold(household_id=UUID(int=1), auth_user_id=UUID(int=2))

    app.dependency_overrides[get_current_household] = household
    return TestClient(app, raise_server_exceptions=False)


def _post(client: TestClient, content: bytes, content_type: str, *, key: str | None = "k", **data: str):
    headers = {"Idempotency-Key": key} if key else {}
    return client.post("/api/v1/documents", files={"file": ("policy.pdf", content, content_type)}, data=data, headers=headers)


def _assert_422(response, field: str) -> dict:
    assert response.status_code == 422, response.text
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "validation_error"
    assert field in {error["field"] for error in body["error"]["field_errors"]}
    return body["error"]


@pytest.mark.parametrize(
    ("content", "expected"),
    [(PDF, "application/pdf"), (PNG, "image/png"), (JPEG, "image/jpeg"), (b"GIF89a....", None), (b"", None), (b"MZ\x90\x00", None)],
)
def test_content_type_is_read_from_the_files_first_bytes(content: bytes, expected: str | None) -> None:
    assert detect_content_type(content) == expected


def test_sha256_identifies_content() -> None:
    assert sha256_hex(PDF) == sha256_hex(bytes(PDF))
    assert sha256_hex(PDF) != sha256_hex(PDF + b" ")
    assert len(sha256_hex(PDF)) == 64


def test_missing_idempotency_key_is_422(upload_client: TestClient, storage: InMemoryStorage) -> None:
    error = _assert_422(_post(upload_client, PDF, "application/pdf", key=None), "Idempotency-Key")

    assert error["message"] == "Idempotency-Key is required on this endpoint."
    assert storage.objects == {}


def test_missing_file_is_422(upload_client: TestClient) -> None:
    response = upload_client.post("/api/v1/documents", headers={"Idempotency-Key": "k"})

    _assert_422(response, "file")


@pytest.mark.parametrize(
    ("content", "declared"),
    [
        (b"GIF89a not allowed", "image/gif"),
        (b"plain text pretending", "application/pdf"),  # declared PDF, is not one
        (b"MZ\x90\x00 an executable", "application/pdf"),
        (PNG, "application/pdf"),  # a real PNG sent as a PDF
        (PDF, "image/png"),  # a real PDF sent as a PNG
        (PDF, "application/octet-stream"),
        (b"", "application/pdf"),
    ],
)
def test_wrong_or_mismatched_file_type_is_422(
    upload_client: TestClient, storage: InMemoryStorage, content: bytes, declared: str
) -> None:
    _assert_422(_post(upload_client, content, declared), "file")

    assert storage.objects == {}, "a rejected file must not be stored"


def test_file_over_25_mb_is_413(upload_client: TestClient, storage: InMemoryStorage) -> None:
    too_big = PDF + b"0" * MAX_UPLOAD_BYTES

    response = _post(upload_client, too_big, "application/pdf")

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"
    assert storage.objects == {}


def test_claim_uploads_are_refused_for_now(upload_client: TestClient, storage: InMemoryStorage) -> None:
    response = _post(upload_client, PDF, "application/pdf", claim_id="01920000-0000-7000-8000-000000000099")

    _assert_422(response, "claim_id")
    assert storage.objects == {}


def test_upload_requires_a_token() -> None:
    client = TestClient(create_app(), raise_server_exceptions=False)

    response = _post(client, PDF, "application/pdf")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
