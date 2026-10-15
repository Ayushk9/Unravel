"""The policy's room-rent cap per day, worked out one way for both the eligibility check and the alert."""

from __future__ import annotations

from dataclasses import dataclass

from contracts.models import CoverageProfile, Extracted

from engines.rules.confidence import lowest, of_extracted
from engines.rules.models import Confidence
from engines.rules.money import format_rupees, percent_cap


@dataclass(frozen=True)
class RoomRentCap:
    per_day: int  # paise
    confidence: Confidence
    # One sentence saying what the cap is and, for a percentage cap, the arithmetic.
    how: str
    clause: Extracted


@dataclass(frozen=True)
class NoCap:
    # Why the cap could not be worked out, in words that fit "In your policy's extracted terms ...".
    reason: str
    clause: Extracted | None


def room_rent_cap(profile: CoverageProfile | None) -> RoomRentCap | NoCap:
    caps = [limit for limit in profile.sub_limits if limit.category == "room_rent"] if profile else []
    if len(caps) != 1:
        return NoCap("no room rent limit was found" if not caps else "more than one room rent limit was found", None)

    limit = caps[0]
    if limit.cap_basis == "per_day" and limit.cap_amount.value is not None:
        cap = limit.cap_amount.value
        return RoomRentCap(cap, of_extracted(limit.cap_amount), f"Your policy caps room rent at {format_rupees(cap)} per day.", limit.cap_amount)
    if limit.cap_basis == "percent_of_sum_insured" and limit.percent_value is not None and profile and profile.sum_insured.value is not None:
        cap = percent_cap(profile.sum_insured.value, limit.percent_value)
        how = (
            f"Your policy caps room rent per day at {limit.percent_value:g} in every 100 of the sum insured: "
            f"{format_rupees(profile.sum_insured.value)} x {limit.percent_value:g} / 100 = {format_rupees(cap)} per day."
        )
        return RoomRentCap(cap, lowest(of_extracted(limit.cap_amount), of_extracted(profile.sum_insured)), how, limit.cap_amount)
    return NoCap("the room rent limit is not stated per day or as a share of the sum insured", limit.cap_amount)
