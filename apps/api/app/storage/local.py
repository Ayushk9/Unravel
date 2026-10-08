"""Local-disk storage: uploaded files kept in a folder on this machine.

The default backend. The demo runs on one Mac with no cloud deployment, so a
folder is the simplest thing that works: nothing to configure, files can be
inspected in Finder, and no network is involved. The folder is gitignored.

Layout on disk mirrors the storage path:

    <root>/<household_id>/<document_id>/<sanitised file name>

SIGNED URLS WITHOUT A CLOUD SERVICE

The provenance viewer needs a link it can load with no Authorization header
(API_DECISIONS D-26). Supabase issues such links itself. Here the API serves
the file from its own route, GET /api/v1/local-files, and the link carries
proof that this server issued it:

    /api/v1/local-files?path=<path>&expires=<unix time>&signature=<hex>

`signature` is an HMAC-SHA256 over "<path>\\n<expires>" using a secret key
only this server knows. To accept a link, the server recomputes the HMAC
from the path and expiry in the URL and compares. Changing the path (to
reach someone else's file) or the expiry (to keep a link alive) changes the
correct signature, and without the key nobody else can compute it.

The key is random and made fresh each time the server starts. Links live for
five minutes, so losing them on a restart costs nothing, and there is no
secret to store or leak.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode

from app.storage.base import StorageError, temporary_file

# Path of the route that serves signed links, relative to the server root.
LOCAL_FILES_ROUTE = "/api/v1/local-files"


class LocalDiskStorage:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._signing_key = secrets.token_bytes(32)

    def _resolve(self, path: str) -> Path:
        """The file on disk for a storage path, refusing anything outside the root.

        Storage paths are built by this application, but the file route also
        receives one from a URL. Resolving the path and checking it is still
        inside the root is what stops "../../etc/passwd".
        """
        candidate = (self._root / path).resolve()
        if not candidate.is_relative_to(self._root) or candidate == self._root:
            raise StorageError("path is outside the storage folder")
        return candidate

    async def save(self, path: str, content: bytes, content_type: str) -> None:
        target = self._resolve(path)
        if target.exists():
            raise StorageError(f"an object already exists at {path}")

        def write() -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

        try:
            # File I/O blocks, so it runs in a helper thread.
            await asyncio.to_thread(write)
        except OSError as exc:
            raise StorageError(f"could not write the file: {exc.strerror}") from exc

    @asynccontextmanager
    async def open_to_tempfile(self, path: str) -> AsyncIterator[Path]:
        source = self._resolve(path)
        try:
            content = await asyncio.to_thread(source.read_bytes)
        except OSError as exc:
            raise StorageError(f"no object at {path}") from exc
        # The parser gets its own copy, never the stored original, so nothing
        # it does can damage the file the user uploaded.
        async with temporary_file(content, source.name) as file_path:
            yield file_path

    async def delete(self, path: str) -> None:
        target = self._resolve(path)
        target.unlink(missing_ok=True)
        # Remove the now-empty <document_id> and <household_id> folders.
        for folder in (target.parent, target.parent.parent):
            if folder != self._root and folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()

    def _signature(self, path: str, expires: int) -> str:
        message = f"{path}\n{expires}".encode()
        return hmac.new(self._signing_key, message, hashlib.sha256).hexdigest()

    async def signed_url(self, path: str, expires_in_seconds: int) -> str:
        """A link relative to this server; the route turns it into a full URL."""
        if not self._resolve(path).is_file():
            raise StorageError(f"no object at {path}")
        expires = int(time.time()) + expires_in_seconds
        query = urlencode({"path": path, "expires": expires, "signature": self._signature(path, expires)})
        return f"{LOCAL_FILES_ROUTE}?{query}"

    def open_signed(self, path: str, expires: int, signature: str) -> Path:
        """The file a signed link points at, or StorageError if the link is not valid."""
        # compare_digest takes the same time whether the first or the last
        # character differs, so response timing reveals nothing about the
        # correct signature.
        if not hmac.compare_digest(self._signature(path, expires), signature):
            raise StorageError("signature does not match")
        if time.time() > expires:
            raise StorageError("link has expired")
        target = self._resolve(path)
        if not target.is_file():
            raise StorageError("file no longer exists")
        return target
