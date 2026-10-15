"""Calendar arithmetic, done one way everywhere.

WAITING-PERIOD END
    A waiting period of N months that starts on S ends on S + N calendar
    months, with the day clamped to the end of a shorter month:
        31 Jan + 1 month  = 28 Feb (29 Feb in a leap year)
        29 Feb 2024 + 12  = 28 Feb 2025
    python-dateutil's relativedelta does exactly this.

BOUNDARY
    An admission ON the end date is OUTSIDE the waiting period: the period
    has been served. An admission one day earlier is inside it. This single
    rule is used by every check and is stated in every explanation.
    (Assumption to verify: some policy wordings say "after the expiry of".)

START OF THE CLOCK
    Waiting periods really run from the first inception of continuously
    renewed cover. If the user has given that date, it is used. Otherwise
    the current policy's start date is used, and every explanation says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

INDIA = ZoneInfo("Asia/Kolkata")

BOUNDARY_NOTE = "An admission on or after the end date counts as outside the waiting period."
ASSUMPTION_START_DATE = (
    "Counted from the policy start date we hold. If your cover has been renewed without a break, "
    "waiting periods usually run from the first policy's start, which could be earlier."
)


@dataclass(frozen=True)
class WaitingClock:
    """The date waiting periods are counted from, and how to talk about it."""

    start: date
    # True when the user gave the first inception date of continuous cover.
    from_first_inception: bool

    @property
    def value_key(self) -> str:
        """The name the date goes under in a check's `values`, so it says which date it is."""
        return "first_inception_date" if self.from_first_inception else "policy_start"

    @property
    def started(self) -> str:
        """Start of a sentence: 'Your policy started 14 Mar 2024'."""
        subject = "Your continuous cover started" if self.from_first_inception else "Your policy started"
        return f"{subject} {format_date(self.start)}"

    @property
    def note(self) -> str:
        if self.from_first_inception:
            return f"Counted from {format_date(self.start)}, the date you gave as the start of your cover with no break since."
        return ASSUMPTION_START_DATE


def waiting_clock(start_date: date | None, first_inception_date: date | None) -> WaitingClock | None:
    """First inception if the user gave it, else the policy start date, else None (not known)."""
    if first_inception_date is not None:
        return WaitingClock(first_inception_date, True)
    if start_date is not None:
        return WaitingClock(start_date, False)
    return None


def add_months(start: date, months: int) -> date:
    """`months` calendar months after `start`, clamped to the last day of the month."""
    return start + relativedelta(months=months)


def months_and_days(earlier: date, later: date) -> tuple[int, int]:
    """Whole calendar months, then remaining days, from `earlier` to `later`.

    2024-03-14 -> 2026-04-02 is (24, 19): 24 months reach 14 Mar 2026, then 19 more days.
    """
    difference = relativedelta(later, earlier)
    return difference.years * 12 + difference.months, difference.days


def india_date(instant: datetime) -> date:
    """The calendar date of an instant as seen in India."""
    return instant.astimezone(INDIA).date()


def hours_to_whole_days(hours: float) -> int:
    """A window in hours as whole days, rounded up: only the admission DATE is known, not the time."""
    whole, remainder = divmod(hours, 24)
    return int(whole) + (1 if remainder > 0 else 0)


def add_days(start: date, days: int) -> date:
    return start + timedelta(days=days)


def format_date(day: date) -> str:
    """14 Mar 2024. The one date format in every explanation."""
    return f"{day.day} {day:%b %Y}"


def format_span(months: int, days: int) -> str:
    """'24 months and 19 days', '1 month', '12 days', '0 days'."""
    parts = []
    if months:
        parts.append(f"{months} month{'' if months == 1 else 's'}")
    if days or not parts:
        parts.append(f"{days} day{'' if days == 1 else 's'}")
    return " and ".join(parts)


def whole_months(value: float | None) -> int | None:
    """A month count as an integer, or None if it is missing or not a whole number.

    A waiting period of, say, 1.5 months cannot be laid on the calendar
    without inventing a conversion, so it is treated as not usable.
    """
    if value is None or value <= 0 or value != int(value):
        return None
    return int(value)
