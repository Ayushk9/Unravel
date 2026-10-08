"""Print every rule in the two rule files, for checking against the sources.

Run from apps/api:
    ../../.venv/bin/python scripts/print_rules.py

Needs no database and no settings: it only reads app/rules/*.yaml.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.rules.loader import load_deadline_rules, load_required_documents  # noqa: E402


def _source(document: str, section: str | None, url: str | None) -> str:
    return f"{document} | {section or 'section: TODO'} | {url or 'url: TODO'}"


def main() -> None:
    deadlines = load_deadline_rules()
    print(f"app/rules/deadline_rules.yaml (file version {deadlines.version})\n")
    print(f"{'id':<24} {'value':<34} {'verified':<9} source")
    print("-" * 150)
    for rule in deadlines.rules:
        trigger = "admission date" if rule.trigger.admission else f"latest '{rule.trigger.event}' event"
        offset = f"{rule.offset.value} {rule.offset.unit}" if rule.offset.value else f"policy's {rule.offset.policy_field}"
        print(f"{rule.id:<24} {offset + ' from ' + trigger:<34} {str(rule.verified).lower():<9} {_source(**rule.source.model_dump())}")
    print(
        f"\n{'urgency thresholds':<24} critical <= {deadlines.urgency.critical_within_days} days, "
        f"soon <= {deadlines.urgency.soon_within_days} days   (a product choice, not a regulation)"
    )

    required = load_required_documents()
    print(f"\n\napp/rules/required_documents.yaml (file version {required.version}, verified: {str(required.verified).lower()})\n")
    print(f"{'claim_type / admission_type':<30} required documents")
    print("-" * 150)
    for claim_type, by_admission in required.checklists.items():
        for admission_type, types in by_admission.items():
            print(f"{claim_type + ' / ' + admission_type:<30} {', '.join(types)}")
    print(f"\n{'document type':<24} {'verified':<9} source")
    print("-" * 150)
    for name, document in required.documents.items():
        print(f"{name:<24} {str(required.verified).lower():<9} {_source(**document.source.model_dump())}")


if __name__ == "__main__":
    main()
