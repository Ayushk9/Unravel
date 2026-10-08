"""Where uploaded files live: the interface, and helpers every backend shares.

The rest of the application talks to `DocumentStorage` only. There are
three implementations, chosen in factory.py:

    local.py      a folder on this machine. The default: the demo runs on
                  one Mac with no cloud deployment.
    supabase.py   a private Supabase Storage bucket, for a hosted deployment
                  where the server's own disk is wiped on every redeploy.
    memory.py     a dictionary, for tests.

A local temporary file exists only while one document is being parsed,
because Engine A reads from a file path. `open_to_tempfile` is a context
manager, so the file is deleted when the block ends, whether the parse
succeeded or raised.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Protocol
from uuid import UUID

# Every temporary directory this app creates starts with this, so leftovers
# can be recognised and removed.
TEMP_DIRECTORY_PREFIX = "unravel-parse-"

_UNSAFE_FILENAME_CHARACTERS = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_FILENAME_LENGTH = 100


class StorageError(Exception):
    """The storage backend could not complete an operation."""


class DocumentStorage(Protocol):
    async def save(self, path: str, content: bytes, content_type: str) -> None:
        """Store `content` at `path`. Fails if something is already there."""

    def open_to_tempfile(self, path: str) -> AbstractAsyncContextManager[Path]:
        """Download `path` to a local temporary file for the duration of a `async with` block."""

    async def delete(self, path: str) -> None:
        """Remove `path`. Removing something that is not there is not an error."""

    async def signed_url(self, path: str, expires_in_seconds: int) -> str:
        """A URL that lets its holder download `path` until it expires."""


def sanitise_filename(file_name: str) -> str:
    """Reduce a user-supplied file name to characters safe in a storage path.

    The name comes from the client, so it cannot be trusted: it may contain
    "../", slashes, spaces or control characters. Only letters, digits, dot,
    underscore and hyphen are kept.
    """
    base_name = file_name.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = _UNSAFE_FILENAME_CHARACTERS.sub("_", base_name).strip("._")
    if not cleaned:
        return "document"
    if len(cleaned) > _MAX_FILENAME_LENGTH:
        # Keep the end, which holds the extension.
        cleaned = cleaned[-_MAX_FILENAME_LENGTH:].lstrip("._") or "document"
    return cleaned


def build_object_path(household_id: UUID, document_id: UUID, file_name: str) -> str:
    """{household_id}/{document_id}/{sanitised file name}.

    The household comes first so one household's files sit under one prefix.
    The document id makes the path unique even when two uploads share a name.
    """
    return f"{household_id}/{document_id}/{sanitise_filename(file_name)}"


@asynccontextmanager
async def temporary_file(content: bytes, file_name: str) -> AsyncIterator[Path]:
    """Write `content` to a temporary file and delete it when the block ends.

    TemporaryDirectory removes the directory and everything in it on exit,
    including when the block raises.
    """
    with tempfile.TemporaryDirectory(prefix=TEMP_DIRECTORY_PREFIX) as directory:
        file_path = Path(directory) / sanitise_filename(file_name)
        file_path.write_bytes(content)
        yield file_path


def remove_stale_temporary_files() -> int:
    """Delete temporary parse directories left by a server that was killed.

    `temporary_file` cleans up after itself on success and on any exception.
    The one case it cannot handle is the process being killed outright
    (kill -9, power loss): no code runs then. This is called at startup to
    remove whatever such a death left behind. Returns how many were removed.

    Like startup job recovery, this assumes a single worker: at startup no
    parse of this process can be in progress, so every such directory is stale.
    """
    removed = 0
    for directory in Path(tempfile.gettempdir()).glob(f"{TEMP_DIRECTORY_PREFIX}*"):
        shutil.rmtree(directory, ignore_errors=True)
        removed += 1
    return removed
