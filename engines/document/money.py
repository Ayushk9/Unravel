"""Indian-rupee text -> integer paise.

Every money field in `contracts.models` is a plain `int` (paise) wrapped in
`Extracted[int]` — never a float, never a `Decimal`. Floats are unsafe for
money (binary rounding error); this module avoids the problem entirely by
never converting to a float at any point, doing every step — comma
stripping, fractional-paise rounding, lakh/crore scaling — as integer
arithmetic on digit strings.

Handles the formats that actually appear in these documents: Indian
lakh/crore digit grouping (`1,00,00,000` = one crore, not "1 million"),
the `Rs.` / `₹` / `/-` decorations, and the spelled-out `lakh` / `lac` /
`crore` multiplier words. Does not attempt to parse fully spelled-out
numbers ("Rupees Five Lakh Only") — not observed in the spike corpus.
"""

from __future__ import annotations

import re

_AMOUNT_PATTERN = re.compile(r"\d[\d,]*(?:\.\d+)?")

_MULTIPLIER_PATTERN = re.compile(r"\b(lakhs?|lacs?|crores?|cr)\b", re.IGNORECASE)
_MULTIPLIER_VALUES = {
    "lakh": 100_000,
    "lakhs": 100_000,
    "lac": 100_000,
    "lacs": 100_000,
    "crore": 10_000_000,
    "crores": 10_000_000,
    "cr": 10_000_000,
}


class MoneyParseError(ValueError):
    """Raised when no rupee amount could be found in the given text."""


def parse_rupees_to_paise(text: str) -> int:
    """Parse an Indian-rupee amount to an integer number of paise.

    Currency symbols, `/-` suffixes, and multiplier/basis words ("per day")
    are ignored rather than stripped up front — the amount regex only ever
    matches a digit run, so surrounding text never contaminates it. Takes
    the *first* digit run in the string, so a string mentioning two amounts
    ("Rs 5,00,000, later revised to Rs 6,00,000") needs to be split by the
    caller before this function sees it.
    """
    if not text or not text.strip():
        raise MoneyParseError("empty amount string")

    match = _AMOUNT_PATTERN.search(text)
    if match is None:
        raise MoneyParseError(f"no numeric amount found in {text!r}")

    whole_str, _, frac_str = match.group(0).replace(",", "").partition(".")
    whole_str = whole_str or "0"

    frac_paise, carry = _round_fraction_to_paise(frac_str)
    whole = int(whole_str) + carry
    base_paise = whole * 100 + frac_paise

    multiplier_match = _MULTIPLIER_PATTERN.search(text)
    multiplier = _MULTIPLIER_VALUES[multiplier_match.group(1).lower()] if multiplier_match else 1

    return base_paise * multiplier


def _round_fraction_to_paise(frac_str: str) -> tuple[int, int]:
    """Round a decimal-rupee fraction to the nearest paise (2 digits).

    Returns (paise_from_fraction in 0..99, carry in {0, 1} rupee) so a
    fraction like ".995" rounds up into the whole-rupee part cleanly. Pure
    integer arithmetic on the digit string — no float involved.
    """
    if not frac_str:
        return 0, 0

    padded = (frac_str + "000")[:3]
    two_digit_paise = int(padded[:2])
    round_up = int(padded[2]) >= 5

    if round_up:
        two_digit_paise += 1
    if two_digit_paise == 100:
        return 0, 1
    return two_digit_paise, 0
