"""Supabase Storage, called over its REST API.

The bucket is PRIVATE: nothing in it is reachable by URL alone. Only this
backend, holding the service-role key, can read or write it. A browser gets
at a file only through a signed URL that this backend issues after checking
the caller owns the document, and that URL stops working after a few minutes.

The four calls used, all under {SUPABASE_URL}/storage/v1:

    POST   /object/{bucket}/{path}        upload
    GET    /object/{bucket}/{path}        download
    DELETE /object/{bucket}/{path}        delete
    POST   /object/sign/{bucket}/{path}   create a signed URL
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

import httpx

from app.storage.base import StorageError, temporary_file

# Uploading or downloading a 25 MB file on a slow connection takes a while.
_TIMEOUT = httpx.Timeout(120.0, connect=10.0)


class SupabaseStorage:
    def __init__(
        self,
        supabase_url: str,
        service_role_key: str,
        bucket: str,
        # Tests pass a fake transport so no real network call is made.
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = f"{supabase_url.rstrip('/')}/storage/v1"
        self._bucket = bucket
        self._transport = transport
        # Supabase expects the key in both headers.
        self._headers = {"Authorization": f"Bearer {service_role_key}", "apikey": service_role_key}

    def _object_url(self, path: str) -> str:
        # quote() keeps "/" so the path stays a path, and escapes anything else.
        return f"{self._base_url}/object/{self._bucket}/{quote(path)}"

    async def _request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers=self._headers, transport=self._transport) as client:
                return await client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise StorageError(f"could not reach file storage: {type(exc).__name__}") from exc

    async def save(self, path: str, content: bytes, content_type: str) -> None:
        response = await self._request(
            "POST",
            self._object_url(path),
            content=content,
            # x-upsert false: refuse to overwrite. Paths contain the document
            # id, so a collision would mean a bug, not a normal re-upload.
            headers={"Content-Type": content_type, "x-upsert": "false"},
        )
        if response.status_code != 200:
            raise StorageError(f"upload failed with status {response.status_code}: {response.text[:200]}")

    @asynccontextmanager
    async def open_to_tempfile(self, path: str) -> AsyncIterator[Path]:
        response = await self._request("GET", self._object_url(path))
        if response.status_code != 200:
            raise StorageError(f"download failed with status {response.status_code}")
        async with temporary_file(response.content, path.rsplit("/", 1)[-1]) as file_path:
            yield file_path

    async def delete(self, path: str) -> None:
        response = await self._request("DELETE", self._object_url(path))
        # Deleting something already gone is fine.
        if response.status_code not in (200, 400, 404):
            raise StorageError(f"delete failed with status {response.status_code}")

    async def signed_url(self, path: str, expires_in_seconds: int) -> str:
        response = await self._request(
            "POST",
            f"{self._base_url}/object/sign/{self._bucket}/{quote(path)}",
            json={"expiresIn": expires_in_seconds},
        )
        if response.status_code != 200:
            raise StorageError(f"could not sign a URL, status {response.status_code}")
        # The API answers with a path relative to /storage/v1.
        return f"{self._base_url}{response.json()['signedURL']}"

    async def ensure_bucket(self) -> bool:
        """Create the private bucket if it does not exist. Returns True if it was created."""
        existing = await self._request("GET", f"{self._base_url}/bucket/{self._bucket}")
        if existing.status_code == 200:
            if existing.json().get("public"):
                raise StorageError(f"bucket {self._bucket!r} exists but is PUBLIC; it must be private")
            return False
        created = await self._request(
            "POST", f"{self._base_url}/bucket", json={"id": self._bucket, "name": self._bucket, "public": False}
        )
        if created.status_code != 200:
            raise StorageError(f"could not create bucket, status {created.status_code}: {created.text[:200]}")
        return True
