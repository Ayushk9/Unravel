from __future__ import annotations

from pathlib import Path

from cache import DiskCache, build_cache_key


def test_get_missing_key_returns_none(tmp_path: Path) -> None:
    cache = DiskCache(cache_dir=tmp_path)
    assert cache.get("nope") is None


def test_set_then_get_round_trips(tmp_path: Path) -> None:
    cache = DiskCache(cache_dir=tmp_path)
    cache.set("k1", {"sum_insured_raw": "5,00,000", "sub_limits": []})
    assert cache.get("k1") == {"sum_insured_raw": "5,00,000", "sub_limits": []}


def test_cache_key_stable_for_same_file_and_version(tmp_path: Path) -> None:
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"same bytes")

    key_a = build_cache_key(f, "policy", "v1")
    key_b = build_cache_key(f, "policy", "v1")

    assert key_a == key_b


def test_cache_key_changes_with_file_content(tmp_path: Path) -> None:
    f1 = tmp_path / "a.pdf"
    f1.write_bytes(b"content A")
    f2 = tmp_path / "b.pdf"
    f2.write_bytes(b"content B")

    assert build_cache_key(f1, "policy", "v1") != build_cache_key(f2, "policy", "v1")


def test_cache_key_changes_with_prompt_version(tmp_path: Path) -> None:
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"same bytes")

    key_v1 = build_cache_key(f, "policy", "v1")
    key_v2 = build_cache_key(f, "policy", "v2")

    assert key_v1 != key_v2


def test_cache_key_changes_with_document_kind(tmp_path: Path) -> None:
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"same bytes")

    assert build_cache_key(f, "policy", "v1") != build_cache_key(f, "bill", "v1")
