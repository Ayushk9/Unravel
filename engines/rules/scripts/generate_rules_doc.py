"""Write docs/RULES.md from the rule registry, so the document cannot drift from the code.

Run from the repo root:
    .venv/bin/python engines/rules/scripts/generate_rules_doc.py

engines/rules/tests/test_rules_doc.py fails if the committed file is out of date.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from engines.rules import PRECEDENT_NOTE, load_reference  # noqa: E402
from engines.rules.alerts import EXPIRING_WITHIN_DAYS, RENEWAL_WITHIN_DAYS  # noqa: E402
from engines.rules.band import __doc__ as BAND_DOC  # noqa: E402
from engines.rules.dates import ASSUMPTION_START_DATE, BOUNDARY_NOTE  # noqa: E402
from engines.rules.money import format_rupees  # noqa: E402
from engines.rules.registry import ALERT_RULES, ELIGIBILITY_RULES  # noqa: E402

OUTPUT = REPO_ROOT / "docs" / "RULES.md"


def _code(items: tuple[str, ...]) -> str:
    return "<br>".join(f"`{item}`" for item in items) or "-"


def render() -> str:
    reference = load_reference()
    lines = [
        "# Engine B rules",
        "",
        "Generated from `engines/rules/registry.py` by `engines/rules/scripts/generate_rules_doc.py`. Do not edit by hand.",
        "",
        "Engine B is a pure function of its inputs: no clock (today's date is passed in), no database, no network, no LLM.",
        "No rule produces a score, probability or percentage. Each check returns a status, a confidence derived from its",
        "inputs, the values it used, a sentence showing the arithmetic, the clause it relied on, and any missing facts.",
        "",
        "## Eligibility checks (Feature 2)",
        "",
        "| Rule | Title | Critical | Extracted fields read | Facts read | Outcomes |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for rule in ELIGIBILITY_RULES:
        lines.append(
            f"| `{rule.id}` | {rule.title} | {'yes' if rule.critical else 'no'} | {_code(rule.reads_extracted)} | "
            f"{_code(rule.reads_facts)} | {rule.outcomes} |"
        )
    lines += [
        "",
        "### Conventions every check follows",
        "",
        f"- **Waiting-period end:** start + N calendar months, clamped to the last day of a shorter month (31 Jan + 1 month = 28 Feb). {BOUNDARY_NOTE}",
        "- **Start of the clock:** the policy's `first_inception_date` (the start of continuous cover) if the user gave it; "
        f"otherwise its `start_date`, and the explanation then says: \"{ASSUMPTION_START_DATE}\"",
        "- **Confidence:** the lowest confidence among the check's inputs. An extracted field counts at its own confidence, or `high` if the user confirmed it. Facts the user entered and policy dates count as `high`. One low-confidence, unconfirmed input stops a check being `high`.",
        "- **Money:** integer paise. A cap stated as a share of the sum insured is `sum_insured x round(percent x 100) // 10000`, rounded down.",
        "- **Disease-specific waiting periods and exclusions** apply only when the user selects them from the policy's own list. Nothing is matched by keyword or by an LLM.",
        "- **Unknown** is returned whenever an input is missing, with the missing fact and where to get it. Nothing is guessed.",
        "",
        "### Band",
        "",
        "```",
        (BAND_DOC or "").strip(),
        "```",
        "",
        f"Ombudsman precedent: always an empty list for now, with the note: \"{PRECEDENT_NOTE}\"",
        "",
        "## Gap alerts (Feature 8)",
        "",
        "Computed on every read for each of the household's policies; nothing is stored or scheduled. An alert whose input is missing is skipped and the reason is logged.",
        "",
        "| Kind | Severity | Reads | Fires when | Skipped when | Uses unverified reference data |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for rule in ALERT_RULES:
        lines.append(
            f"| `{rule.kind}` | {rule.severity} | {_code(rule.reads)} | {rule.fires_when} | {rule.skipped_when} | "
            f"{'yes' if rule.uses_reference_data else 'no'} |"
        )
    lines += [
        "",
        f"Windows: waiting period ending within {EXPIRING_WITHIN_DAYS} days; policy ending within {RENEWAL_WITHIN_DAYS} days.",
        "",
        "## Reference figures (`engines/rules/reference/typical_costs.yaml`)",
        "",
        "| Figure | Value | Source | Verified |",
        "| --- | --- | --- | --- |",
    ]
    source = reference.low_sum_insured_source
    for band in reference.low_sum_insured:
        who = f"household of up to {band.members_up_to}" if band.members_up_to < 99 else "larger household"
        lines.append(f"| Minimum sum insured, {who} | {format_rupees(band.minimum_paise)} | {source.document} | {str(source.verified).lower()} |")
    room_source = reference.typical_room_rent_source
    for city_kind, paise in reference.typical_room_rent_per_day.items():
        lines.append(f"| Typical room rent per day, {city_kind} (unused: no city stored) | {format_rupees(paise)} | {room_source.document} | {str(room_source.verified).lower()} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    OUTPUT.write_text(render(), encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
