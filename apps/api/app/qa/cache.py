"""The Q&A answer cache: one JSON file per key, kept for 24 hours (D-42).

Key = SHA-256 of (document hash, normalised question, prompt version, model).

  document hash        a different policy file, or a re-uploaded changed one, misses
  normalised question  "Room rent?" and "room   rent?" hit the same entry
  prompt version       changing a prompt or a schema invalidates old answers
  model                a different model may answer differently

A hit returns the stored result and makes no model call at all: no rewrite,
no embedding, no generation, no judging. The rewrite of a Hindi question is
cached separately (rewrite_key), because the same Hindi question can be asked
of different policies.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

TTL_SECONDS = 24 * 60 * 60
CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache" / "qa"


def _digest(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def answer_key(document_hash: str, normalised_question: str, prompt_version: str, model: str) -> str:
    return "answer-" + _digest(document_hash, normalised_question, prompt_version, model)


def rewrite_key(normalised_question: str, prompt_version: str, model: str) -> str:
    return "rewrite-" + _digest(normalised_question, prompt_version, model)


class QaCache:
    def __init__(self, directory: Path = CACHE_DIR, ttl_seconds: float = TTL_SECONDS) -> None:
        self._directory = directory
        self._ttl = ttl_seconds

    def get(self, key: str) -> Any | None:
        path = self._directory / f"{key}.json"
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return None
        if time.time() - entry.get("stored_at", 0) > self._ttl:
            path.unlink(missing_ok=True)
            return None
        return entry["value"]

    def set(self, key: str, value: Any) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        path = self._directory / f"{key}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"stored_at": time.time(), "value": value}, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)  # atomic: a reader never sees half a file
