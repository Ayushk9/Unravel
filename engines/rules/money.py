"""Money: integer paise throughout, formatted only for sentences."""

from __future__ import annotations

BASIS_POINTS_PER_WHOLE = 10_000


def percent_cap(sum_insured_paise: int, percent: float) -> int:
    """A cap of `percent` of the sum insured, in whole paise, with integer arithmetic only.

    The percentage is first turned into basis points (1% = 100 bp) and
    rounded once, so no fractional paise ever appear:
        1% of Rs 10,00,000 = 10,00,00,000 paise x 100 bp // 10,000 = 10,00,000 paise (Rs 10,000).
    The result is rounded down, never up: the cap is never overstated.
    """
    basis_points = round(percent * 100)
    return sum_insured_paise * basis_points // BASIS_POINTS_PER_WHOLE


def format_rupees(paise: int) -> str:
    """Rs amount with Indian digit grouping: 5000000 paise -> '₹50,000'; 50000000 -> '₹5,00,000'."""
    rupees, remainder = divmod(paise, 100)
    digits = str(rupees)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups) + "," + tail
    return f"₹{digits}" + (f".{remainder:02d}" if remainder else "")
