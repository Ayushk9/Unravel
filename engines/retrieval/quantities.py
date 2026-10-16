"""The deterministic number check.

Every number an answer sentence states must be present in the clause it
cites. This does not ask a model; it reads the digits. It is the reason a
sentence that says "Rs 10,000" while citing a clause that says "Rs 5,000"
can never reach the user, however fluent it is.

A number is read as one of four kinds, each normalised so that different
spellings of the same amount compare equal:

    money     "₹5,000", "Rs. 5000/-", "5 lakh", "Rs 1.5 crore"  -> paise (int),
              parsed by Engine A's parse_rupees_to_paise, the same code that
              reads amounts out of policies
    percent   "10%", "10 percent", "10 per cent"                -> "10"
    duration  "48 months", "4 years", "30 days", "24 hours"     -> (unit, count);
              years are counted as months (x12), because policies state the
              same waiting period either way. Days are never converted to months.
    number    any other digit run, such as a section number     -> "4.2"

Matching is exact on (kind, value), with one allowance: a clause often states
an amount or a duration without its unit ("Room rent 5000 per day"), so a
sentence quantity also matches a bare number in the clause with the same value.

Numbers written as words ("thirty days") are not read. The answer prompt asks
for digits; a clause that uses words simply fails this check, which removes
the sentence. That is the safe direction to be wrong in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from engines.document.money import MoneyParseError, parse_rupees_to_paise
from engines.retrieval.language import ascii_digits

_NUM = r"\d[\d,]*(?:\.\d+)?"
_MULTIPLIER = r"lakhs?|lacs?|crores?|cr"

# Order matters: money first, then percentages and durations, then whatever digits are left.
_MONEY = re.compile(
    rf"(?:(?:₹|(?<![a-z])(?:rs\.?|inr|rupees?))\s*{_NUM}(?:\s*(?:{_MULTIPLIER})\b)?"
    rf"|{_NUM}\s*(?:{_MULTIPLIER})\b"
    rf"|{_NUM}\s*(?:/-|rupees?\b))",
    re.IGNORECASE,
)
_PERCENT = re.compile(rf"({_NUM})\s*(?:%|per\s?cent\b|percent\b)", re.IGNORECASE)
_DURATION = re.compile(rf"({_NUM})\s*(days?|months?|years?|yrs?|hours?|hrs?)\b", re.IGNORECASE)
_BARE = re.compile(_NUM)

_UNIT = {"day": "days", "month": "months", "year": "months", "yr": "months", "hour": "hours", "hr": "hours"}


@dataclass(frozen=True, order=True)
class Quantity:
    kind: str  # money | percent | days | months | hours | number
    value: str  # canonical text of the value, so Decimal("5000") and "5,000" compare equal

    def __str__(self) -> str:
        return f"{self.value} ({self.kind})"


def _decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace(",", "")).normalize()
    except InvalidOperation:
        return None


def _canonical(number: Decimal) -> str:
    # normalize() turns 5000 into 5E+3; format it back as plain digits.
    return format(number, "f")


def extract_quantities(text: str) -> set[Quantity]:
    """Every number in `text`, read as money, a percentage, a duration or a plain number."""
    text = ascii_digits(text)
    found: set[Quantity] = set()
    taken: list[tuple[int, int]] = []

    def free(start: int, end: int) -> bool:
        return all(end <= s or start >= e for s, e in taken)

    for match in _MONEY.finditer(text):
        try:
            paise = parse_rupees_to_paise(match.group(0))
        except MoneyParseError:
            continue
        found.add(Quantity("money", str(paise)))
        taken.append(match.span())

    for match in _PERCENT.finditer(text):
        if free(*match.span()) and (value := _decimal(match.group(1))) is not None:
            found.add(Quantity("percent", _canonical(value)))
            taken.append(match.span())

    for match in _DURATION.finditer(text):
        if not free(*match.span()) or (value := _decimal(match.group(1))) is None:
            continue
        unit_word = match.group(2).lower().rstrip("s")
        unit = _UNIT[unit_word]
        if unit_word in ("year", "yr"):
            value = value * 12
        found.add(Quantity(unit, _canonical(value.normalize())))
        taken.append(match.span())

    for match in _BARE.finditer(text):
        if free(*match.span()) and (value := _decimal(match.group(0))) is not None:
            found.add(Quantity("number", _canonical(value)))
    return found


def _bare_value(quantity: Quantity) -> str:
    """The number a quantity would be written as without its unit."""
    if quantity.kind == "money":
        return _canonical((Decimal(quantity.value) / 100).normalize())
    return quantity.value


def is_present(quantity: Quantity, available: set[Quantity]) -> bool:
    """Is this sentence quantity stated in the available text?"""
    if quantity in available:
        return True
    bare = _bare_value(quantity)
    if Quantity("number", bare) in available:
        return True
    # A bare number in the sentence is satisfied by the same value with any unit in the clause.
    return quantity.kind == "number" and any(_bare_value(other) == quantity.value for other in available)


def missing_numbers(sentence: str, sources: list[str]) -> list[Quantity]:
    """The sentence's quantities that appear in none of the sources. Empty means the check passes."""
    available: set[Quantity] = set()
    for source in sources:
        available |= extract_quantities(source)
    return sorted(q for q in extract_quantities(sentence) if not is_present(q, available))
