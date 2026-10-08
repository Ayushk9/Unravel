"""The rule files are validated on load, and the migration's SQL matches the shared copy."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.db import claim_event_ddl
from app.rules.loader import DEADLINE_RULES_FILE, REQUIRED_DOCUMENTS_FILE, DeadlineRules, RequiredDocuments

MIGRATION = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0003_claims.py"


def _deadline_data() -> dict:
    return yaml.safe_load(DEADLINE_RULES_FILE.read_text(encoding="utf-8"))


def test_both_files_load() -> None:
    DeadlineRules.model_validate(_deadline_data())
    RequiredDocuments.model_validate(yaml.safe_load(REQUIRED_DOCUMENTS_FILE.read_text(encoding="utf-8")))


@pytest.mark.parametrize(
    "break_it",
    [
        lambda d: d["rules"][1]["trigger"].update(event="denyed"),  # misspelt state
        lambda d: d["rules"][1]["offset"].update(unit="fortnights"),
        lambda d: d["rules"][1].update(active_in=["under_reveiw"]),
        lambda d: d["rules"][1].pop("source"),
        lambda d: d["rules"][1].pop("verified"),
        lambda d: d["rules"][1].update(verfied=True),  # misspelt key
        lambda d: d["rules"][1]["offset"].update(policy_field="intimation_deadline_hours"),  # both kinds of offset
        lambda d: d["rules"].append(dict(d["rules"][1])),  # duplicate id
    ],
)
def test_a_mistake_in_the_deadline_file_is_caught_on_load(break_it) -> None:
    data = _deadline_data()
    break_it(data)

    with pytest.raises(ValidationError):
        DeadlineRules.model_validate(data)


def test_a_document_type_outside_the_contract_is_caught_on_load() -> None:
    data = yaml.safe_load(REQUIRED_DOCUMENTS_FILE.read_text(encoding="utf-8"))
    data["checklists"]["cashless"]["emergency"].append("claim_form")

    with pytest.raises(ValidationError):
        RequiredDocuments.model_validate(data)


def test_no_source_url_has_been_invented() -> None:
    """Until a person fills one in, every url is null rather than a plausible-looking guess."""
    urls = [rule["source"]["url"] for rule in _deadline_data()["rules"]]

    assert urls == [None] * len(urls)


def _squash(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


@pytest.mark.parametrize("statement", claim_event_ddl.CREATE_STATEMENTS + claim_event_ddl.DROP_STATEMENTS)
def test_migration_contains_the_same_sql_as_the_shared_module(statement: str) -> None:
    assert _squash(statement) in _squash(MIGRATION.read_text(encoding="utf-8"))
