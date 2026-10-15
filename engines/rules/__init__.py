"""Engine B: the deterministic rules engine.

A pure library, like Engine A's parse_and_extract: inputs in, a typed result
out. It has no web framework, no database, no network, no LLM and no clock.
Today's date is always passed in. The same inputs always give the same
answer, which is what makes every verdict reproducible and testable.

Public API:

    assess_eligibility(EligibilityInput, today) -> Assessment     (Feature 2)
    compute_alerts(AlertInput, reference, today) -> AlertsOutcome  (Feature 8)
    RULES                                                          the registry

No score, probability or percentage is produced anywhere. Outcomes are
statuses (satisfied / at_risk / failed / unknown) with the arithmetic that
produced them.
"""

from __future__ import annotations

from datetime import date

from engines.rules.alerts import Reference, compute_alerts, load_reference
from engines.rules.band import decide_band, order_checks
from engines.rules.models import Assessment, EligibilityInput

PRECEDENT_NOTE = "Precedent corpus not yet loaded, so no similar Ombudsman cases are shown."


def assess_eligibility(data: EligibilityInput, today: date) -> Assessment:
    """Run every eligibility rule and decide the band.

    `today` is accepted for symmetry with the alerts and so a future rule
    that needs it cannot quietly read the clock instead. If the coverage
    profile is missing, only that check is returned: nothing else can be
    judged without it.
    """
    from engines.rules.registry import ELIGIBILITY_RULES

    rules = ELIGIBILITY_RULES if data.coverage_profile is not None else ELIGIBILITY_RULES[:1]
    checks = [rule.evaluate(data) for rule in rules]
    band = decide_band(checks)
    return Assessment(band=band, checks=order_checks(checks, band), precedent_note=PRECEDENT_NOTE)


__all__ = ["PRECEDENT_NOTE", "Reference", "assess_eligibility", "compute_alerts", "load_reference"]
