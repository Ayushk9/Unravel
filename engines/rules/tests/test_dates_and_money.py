from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from engines.rules.dates import add_months, format_date, format_span, hours_to_whole_days, india_date, months_and_days, whole_months
from engines.rules.money import format_rupees, percent_cap


@pytest.mark.parametrize(
    ("start", "months", "end"),
    [
        (date(2024, 3, 14), 48, date(2028, 3, 14)),  # the panel scenario
        (date(2026, 1, 31), 1, date(2026, 2, 28)),  # 31 Jan + 1 month, not a leap year
        (date(2028, 1, 31), 1, date(2028, 2, 29)),  # leap year
        (date(2024, 2, 29), 12, date(2025, 2, 28)),  # 29 Feb start
        (date(2024, 2, 29), 48, date(2028, 2, 29)),
        (date(2026, 8, 31), 1, date(2026, 9, 30)),
        (date(2026, 12, 15), 1, date(2027, 1, 15)),
    ],
)
def test_calendar_months_clamp_to_the_end_of_the_month(start: date, months: int, end: date) -> None:
    assert add_months(start, months) == end


@pytest.mark.parametrize(
    ("earlier", "later", "span"),
    [
        (date(2024, 3, 14), date(2026, 4, 2), (24, 19)),
        (date(2026, 4, 2), date(2028, 3, 14), (23, 12)),
        # Consistent with add_months: 31 Jan + 1 month IS 28 Feb, so that span is one month.
        (date(2026, 1, 31), date(2026, 2, 28), (1, 0)),
        (date(2026, 1, 15), date(2026, 1, 15), (0, 0)),
    ],
)
def test_months_and_days_between_dates(earlier: date, later: date, span: tuple[int, int]) -> None:
    assert months_and_days(earlier, later) == span


def test_formatting() -> None:
    assert format_date(date(2026, 4, 2)) == "2 Apr 2026"
    assert format_span(24, 19) == "24 months and 19 days"
    assert format_span(1, 0) == "1 month"
    assert format_span(0, 1) == "1 day"
    assert format_span(0, 0) == "0 days"


@pytest.mark.parametrize(("value", "months"), [(48.0, 48), (1, 1), (1.5, None), (None, None), (0, None), (-3, None)])
def test_only_whole_positive_months_are_usable(value, months) -> None:
    assert whole_months(value) == months


@pytest.mark.parametrize(("hours", "days"), [(24, 1), (24.0, 1), (25, 2), (48, 2), (1, 1), (720, 30)])
def test_hours_round_up_to_whole_days(hours: float, days: int) -> None:
    assert hours_to_whole_days(hours) == days


def test_instants_are_dated_in_india() -> None:
    assert india_date(datetime(2026, 3, 31, 20, 0, tzinfo=timezone.utc)) == date(2026, 4, 1)


@pytest.mark.parametrize(
    ("sum_insured", "percent", "cap"),
    [
        (100_000_000, 1.0, 1_000_000),  # 1% of Rs 10,00,000 = Rs 10,000
        (50_000_000, 1.0, 500_000),
        (50_000_000, 0.5, 250_000),
        (33_333_333, 1.0, 333_333),  # rounds down to whole paise, never up
        (50_000_000, 2.25, 1_125_000),
    ],
)
def test_percent_caps_use_integer_paise(sum_insured: int, percent: float, cap: int) -> None:
    result = percent_cap(sum_insured, percent)

    assert result == cap and type(result) is int


@pytest.mark.parametrize(
    ("paise", "text"),
    [(500_000, "₹5,000"), (50_000_000, "₹5,00,000"), (18_500_000, "₹1,85,000"), (1_000_000_000, "₹1,00,00,000"), (99, "₹0.99"), (12_345_678, "₹1,23,456.78")],
)
def test_rupees_use_indian_digit_grouping(paise: int, text: str) -> None:
    assert format_rupees(paise) == text
