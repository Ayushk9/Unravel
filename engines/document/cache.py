"""Disk cache for LLM extraction results, keyed by (file content hash + prompt version).

Gemini free tier is rate-limited and this pipeline gets re-run constantly
during development — a second run over an unchanged file must make zero API
calls. Keying on the file's own content hash (rather than its path) means a
renamed or copied file still hits the cache, and keying on a prompt version
alongside it means changing the extraction prompt or schema invalidates
stale entries automatically instead of silently returning results shaped
for an older schema.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

DEFAULT_CACHE_DIR = Path(__file__).resolve().parent / ".cache" / "llm"


def build_cache_key(file_path: Path, document_kind: str, prompt_version: str) -> str:
    digest = hashlib.sha256()
    digest.update(file_path.read_bytes())
    digest.update(b"\0")
    digest.update(document_kind.encode("utf-8"))
    digest.update(b"\0")
    digest.update(prompt_version.encode("utf-8"))
    return digest.hexdigest()


class DiskCache:
    """One JSON file per key, no eviction, no locking.

    This is a single-developer, single-process dev-loop cache for a
    capstone build, not a production cache — concurrent-writer safety and
    expiry are out of scope at this scale.
    """

    def __init__(self, cache_dir: Path = DEFAULT_CACHE_DIR) -> None:
        self._cache_dir = cache_dir

    def get(self, key: str) -> Any | None:
        path = self._path_for(key)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def set(self, key: str, value: Any) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._path_for(key).write_text(json.dumps(value), encoding="utf-8")

    def _path_for(self, key: str) -> Path:
        return self._cache_dir / f"{key}.json"
