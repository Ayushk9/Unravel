"""Q&A pieces that need no database: the cache, answer-shape checks, keyword terms, the vector literal."""

from __future__ import annotations

import json
import time
from pathlib import Path

from app.db.vector_type import from_vector_literal, to_vector_literal
from app.qa.cache import QaCache, answer_key, rewrite_key
from app.qa.llm import AnswerSentence, GeneratedAnswer, generated_answer_problems
from app.qa.retrieval import keyword_terms


def test_cache_round_trip_and_expiry(tmp_path: Path) -> None:
    cache = QaCache(tmp_path, ttl_seconds=60)
    cache.set("k", {"answer": "x"})

    assert cache.get("k") == {"answer": "x"}

    path = tmp_path / "k.json"
    entry = json.loads(path.read_text())
    entry["stored_at"] = time.time() - 61
    path.write_text(json.dumps(entry))
    assert cache.get("k") is None and not path.exists(), "an entry older than 24 h is a miss, and is removed"


def test_cache_keys_change_with_every_part() -> None:
    base = answer_key("id", "hash", "room rent?", "qa-v1", "gemini")

    assert base == answer_key("id", "hash", "room rent?", "qa-v1", "gemini")
    variants = {
        base,
        answer_key("id2", "hash", "room rent?", "qa-v1", "gemini"),  # same file, another document (another upload or household)
        answer_key("id", "hash2", "room rent?", "qa-v1", "gemini"),
        answer_key("id", "hash", "icu?", "qa-v1", "gemini"),
        answer_key("id", "hash", "room rent?", "qa-v2", "gemini"),
        answer_key("id", "hash", "room rent?", "qa-v1", "other"),
    }
    assert len(variants) == 6
    assert rewrite_key("q", "qa-v1", "m") != answer_key("", "", "q", "qa-v1", "m")


def test_answer_shape_problems() -> None:
    ids = {"c1", "c2"}
    good = GeneratedAnswer(abstain=False, sentences=[AnswerSentence(text="x", chunk_ids=["c1"])])

    assert generated_answer_problems(good, ids) is None
    assert generated_answer_problems(GeneratedAnswer(abstain=True, reason="no"), ids) is None
    assert "c9" in generated_answer_problems(GeneratedAnswer(abstain=False, sentences=[AnswerSentence(text="x", chunk_ids=["c9"])]), ids)
    assert generated_answer_problems(GeneratedAnswer(abstain=False), ids) == "did not abstain but gave no sentences"
    assert generated_answer_problems(GeneratedAnswer(abstain=True, sentences=good.sentences), ids) == "abstained but also gave sentences"


def test_keyword_terms_are_ored_and_cannot_inject_query_syntax() -> None:
    assert keyword_terms("What is the room-rent cap?") == "what | is | the | room | rent | cap"
    assert keyword_terms("rent & !(cap) | x:*") == "rent | cap"
    assert keyword_terms("? ! .") is None


def test_vector_literal_round_trip() -> None:
    values = [0.1, -0.25, 1.0]

    assert from_vector_literal(to_vector_literal(values)) == values
