"""The overall band: a fixed function of the checks. No score, no weighting.

Applied strictly in this order; the first that matches decides:

  1. insufficient_information   a CRITICAL check is unknown
  2. likely_ineligible          a check failed, with high confidence
  3. at_risk                    a check failed with less than high confidence,
                                or a check is at risk
  4. likely_eligible            otherwise

Why unknown comes before failed: an assessment that is missing a fact which
could change the outcome must say so, rather than show a verdict built on
what it happened to know.

Critical checks are those that decide whether a claim is covered at all
(coverage details, waiting periods, exclusions). A non-critical check that
is unknown (room rent not given, say) is listed with its missing fact but
does not by itself stop "likely eligible".
"""

from __future__ import annotations

from engines.rules.models import Band, CheckResult


def decide_band(checks: tuple[CheckResult, ...] | list[CheckResult]) -> Band:
    if any(check.critical and check.status == "unknown" for check in checks):
        return "insufficient_information"
    if any(check.status == "failed" and check.confidence == "high" for check in checks):
        return "likely_ineligible"
    if any(check.status in ("failed", "at_risk") for check in checks):
        return "at_risk"
    return "likely_eligible"


_DEFAULT_ORDER = {"failed": 0, "at_risk": 1, "unknown": 2, "satisfied": 3}
_MISSING_FIRST = {"unknown": 0, "failed": 1, "at_risk": 2, "satisfied": 3}


def order_checks(checks: list[CheckResult], band: Band) -> tuple[CheckResult, ...]:
    """Missing facts first when information is insufficient; otherwise the worst first.

    sorted() is stable, so checks with the same status keep registry order.
    """
    rank = _MISSING_FIRST if band == "insufficient_information" else _DEFAULT_ORDER
    return tuple(sorted(checks, key=lambda check: (rank[check.status], not check.critical)))
