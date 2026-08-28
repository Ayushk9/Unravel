"""Unit tests for parse_rupees_to_paise, covering every format listed in the
Engine A task brief plus the rounding/edge cases that fall out of the
lakh-crore digit grouping."""

from __future__ import annotations

import pytest

from money import MoneyParseError, parse_rupees_to_paise


@pytest.mark.parametrize(
    "text,expected_paise",
    [
        ("Rs.5,00,000/-", 50_000_000),
        ("₹5,000 per day", 500_000),
        ("5 lakh", 50_000_000),
        ("10 Lacs", 100_000_000),
        ("1,00,00,000/-", 1_000_000_000),  # one crore, per the task's own worked example
        ("Up to Rs.6,000/-", 600_000),
        ("2,500/-", 250_000),
    ],
)
def test_documented_formats(text: str, expected_paise: int) -> None:
    assert parse_rupees_to_paise(text) == expected_paise


def test_crore_word() -> None:
    assert parse_rupees_to_paise("Rs 1 Crore") == 10_000_000_00


def test_lakh_singular_and_lac_variants() -> None:
    assert parse_rupees_to_paise("1 lac") == parse_rupees_to_paise("1 lakh")


def test_fractional_lakh_scales_before_and_after_decimal_correctly() -> None:
    # 1.5 lakh = 150,000 rupees = 15,000,000 paise
    assert parse_rupees_to_paise("1.5 lakh") == 15_000_000


def test_plain_decimal_rupees_rounds_to_nearest_paise() -> None:
    assert parse_rupees_to_paise("100.5") == 10_050
    assert parse_rupees_to_paise("100.999") == 10_100  # rounds the 3rd digit, carries into paise
    assert parse_rupees_to_paise("99.995") == 10_000  # carries into the whole-rupee part


def test_no_multiplier_no_symbols() -> None:
    assert parse_rupees_to_paise("500000") == 50_000_000


def test_no_digits_raises() -> None:
    with pytest.raises(MoneyParseError):
        parse_rupees_to_paise("insufficient information")


def test_empty_string_raises() -> None:
    with pytest.raises(MoneyParseError):
        parse_rupees_to_paise("")


def test_whitespace_only_raises() -> None:
    with pytest.raises(MoneyParseError):
        parse_rupees_to_paise("   ")


def test_takes_first_amount_when_multiple_present() -> None:
    assert parse_rupees_to_paise("Rs 5,00,000 (revised from Rs 4,00,000)") == 50_000_000
