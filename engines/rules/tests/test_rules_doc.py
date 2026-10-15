from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "generate_rules_doc.py"


def test_docs_rules_md_matches_the_registry() -> None:
    spec = importlib.util.spec_from_file_location("generate_rules_doc", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.OUTPUT.read_text(encoding="utf-8") == module.render(), (
        "docs/RULES.md is out of date: run .venv/bin/python engines/rules/scripts/generate_rules_doc.py"
    )
