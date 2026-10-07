"""In-memory storage for tests. Same behaviour as the real one, no network."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from app.storage.base import StorageError, temporary_file


class InMemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        # Every temporary path handed out, so a test can check it was deleted.
        self.temp_paths: list[Path] = []

    async def save(self, path: str, content: bytes, content_type: str) -> None:
        if path in self.objects:
            raise StorageError(f"an object already exists at {path}")
        self.objects[path] = content

    @asynccontextmanager
    async def open_to_tempfile(self, path: str) -> AsyncIterator[Path]:
        if path not in self.objects:
            raise StorageError(f"no object at {path}")
        async with temporary_file(self.objects[path], path.rsplit("/", 1)[-1]) as file_path:
            self.temp_paths.append(file_path)
            yield file_path

    async def delete(self, path: str) -> None:
        self.objects.pop(path, None)

    async def signed_url(self, path: str, expires_in_seconds: int) -> str:
        if path not in self.objects:
            raise StorageError(f"no object at {path}")
        return f"https://storage.test/{path}?token=test&expires_in={expires_in_seconds}"
