"""Provenance survival: does each extracted field's highlight actually contain its value?

For every field Engine A extracted from the Star policy, this reads the PDF's
own text inside the stored page + bbox and checks that the extracted value is
there. It reads the parser's answer (`_original_value`), never a user's
correction, so the rate measures the parser alone.

    fields checked   every extracted field with a value
    contained        the text inside its highlight contains that value
    failures         the value is not in the highlight, or no page/bbox was stored

How a value is matched, by kind:

    money (paise)    the rupee amount in any Indian format: 25,00,000 / 2500000 /
                     25 lakh / 2.5 lakhs / 1 crore, with or without Rs. or the rupee sign
    percent          the number followed by % or "percent" (10% / 10 %)
    hours, months    the number, in digits or words, then the unit: "24 hours",
                     "36 (thirty six) months", "thirty-six months"; months may also
                     be whole years ("2 years" for 24 months)
    text             the whole value, ignoring case, punctuation and line breaks

A sub-limit whose basis is a percent of the sum insured is checked by its
percent. No model call, no gold file: the PDF's text is the only reference.

Run from apps/api against the local database (the Star policy must be uploaded):
    ../../.venv/bin/python scripts/check_provenance.py [policy_id]
"""

from __future__ import annotations

import asyncio
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pypdfium2 as pdfium  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.models import CoverageProfile, Document, Exclusion, SubLimit, WaitingPeriod  # noqa: E402
from app.db.session import create_engine, create_session_factory  # noqa: E402
from app.qa.demo_policy import find_real_policy  # noqa: E402
from app.storage.factory import create_storage  # noqa: E402


@dataclass(frozen=True)
class Field:
    name: str
    kind: str  # money | percent | hours | months | text
    value: object
    provenance: dict | None


# --- reading the highlight ---


def text_in_bbox(pdf: pdfium.PdfDocument, page: int, bbox: list[float]) -> str:
    """The PDF's text inside a normalised top-left-origin bbox (D-23) on a 1-indexed page."""
    pdf_page = pdf[page - 1]
    width, height = pdf_page.get_size()
    x0, y0, x1, y1 = bbox
    # PDF coordinates have their origin at the bottom-left, so y is flipped.
    return pdf_page.get_textpage().get_text_bounded(left=x0 * width, bottom=(1 - y1) * height, right=x1 * width, top=(1 - y0) * height)


# --- matching a value in that text ---

_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}


def number_words(n: int) -> list[str]:
    """How a whole number up to 99 can be written in words: "thirty six" and "thirty-six"."""
    if n < 20:
        return [_ONES[n]]
    tens = next(word for word, value in _TENS.items() if value == n - n % 10)
    return [tens] if n % 10 == 0 else [f"{tens} {_ONES[n % 10]}", f"{tens}-{_ONES[n % 10]}"]


def normalise(text: str) -> str:
    text = text.replace("-\r\n", "").replace("-\n", "")  # a word broken across lines
    return re.sub(r"\s+", " ", text).strip().lower()


# A number with Indian or Western digit grouping, then an optional lakh / crore.
_AMOUNT = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(lakhs?|lacs?|crores?)?")
_MULTIPLIER = {"lakh": 100_000, "lac": 100_000, "crore": 10_000_000}


def has_money(text: str, paise: int) -> bool:
    rupees = paise / 100
    for match in _AMOUNT.finditer(normalise(text)):
        number = float(match.group(1).replace(",", "").rstrip(".") or "nan")
        unit = (match.group(2) or "").rstrip("s")
        if abs(number * _MULTIPLIER.get(unit, 1) - rupees) < 0.005:
            return True
    return False


def has_quantity(text: str, value: float, units: tuple[str, ...]) -> bool:
    """`value` written in digits or words, optionally followed by "(words)", then one of `units`."""
    if value != int(value):
        return False
    n = int(value)
    spellings = [str(n), *number_words(n)] if n < 100 else [str(n)]
    unit = "|".join(units)
    for spelling in spellings:
        pattern = rf"(?<![\w.]){re.escape(spelling)}\s*(\([a-z\s-]+\)\s*)?(?:{unit})"
        if re.search(pattern, normalise(text)):
            return True
    return False


def has_percent(text: str, value: float) -> bool:
    number = f"{value:g}"
    return re.search(rf"(?<![\d.]){re.escape(number)}\s*(%|percent|per cent)", normalise(text)) is not None


def has_text(text: str, value: str) -> bool:
    def bare(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", normalise(s)).strip()

    return bare(value) in bare(text)


def contains(text: str, field: Field) -> bool:
    if field.kind == "money":
        return has_money(text, int(field.value))
    if field.kind == "percent":
        return has_percent(text, float(field.value))
    if field.kind == "hours":
        return has_quantity(text, float(field.value), ("hours?", "hrs?"))
    if field.kind == "months":
        months = float(field.value)
        in_months = has_quantity(text, months, ("months?",))
        in_years = months % 12 == 0 and has_quantity(text, months / 12, ("years?",))
        return in_months or in_years
    return has_text(text, str(field.value))


def why_not(text: str, field: Field) -> str:
    """A plain description of a failure, to read alongside it. It never turns a failure into a pass."""
    if field.kind == "text":
        words = re.findall(r"[a-z0-9]+", normalise(str(field.value)))
        present = set(re.findall(r"[a-z0-9]+", normalise(text)))
        return f" ({sum(word in present for word in words)} of its {len(words)} words are; the stored value is not a quote)"
    if field.kind == "months" and has_quantity(text, float(field.value) * 30, ("days?",)):
        return f" (it states {int(float(field.value) * 30)} days, not months)"
    return ""


# --- the fields, read from the database ---


async def load_fields(session, policy_id: UUID) -> list[Field]:
    profile = await session.scalar(select(CoverageProfile).where(CoverageProfile.policy_id == policy_id))
    if profile is None:
        raise SystemExit("That policy has no coverage profile.")
    fields = [
        Field("sum_insured", "money", profile.sum_insured_original_value, profile.sum_insured_provenance),
        Field("co_pay_percent", "percent", profile.co_pay_percent_original_value, profile.co_pay_percent_provenance),
        Field("intimation_deadline_hours", "hours", profile.intimation_deadline_hours_original_value, profile.intimation_deadline_hours_provenance),
    ]
    for row in await session.scalars(select(SubLimit).where(SubLimit.coverage_profile_id == profile.id).order_by(SubLimit.position)):
        name = f"sub_limit[{row.position}] {row.label}"
        if row.cap_basis == "percent_of_sum_insured":
            fields.append(Field(name + " (percent)", "percent", row.percent_value, row.cap_amount_provenance))
        else:
            fields.append(Field(name, "money", row.cap_amount_original_value, row.cap_amount_provenance))
    for row in await session.scalars(select(WaitingPeriod).where(WaitingPeriod.coverage_profile_id == profile.id).order_by(WaitingPeriod.position)):
        fields.append(Field(f"waiting_period[{row.position}] {row.kind}", "months", row.months_original_value, row.months_provenance))
    for row in await session.scalars(select(Exclusion).where(Exclusion.coverage_profile_id == profile.id).order_by(Exclusion.position)):
        fields.append(Field(f"exclusion[{row.position}]", "text", row.text_original_value, row.text_provenance))
    return fields


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    factory = create_session_factory(engine)
    async with factory() as session:
        policy = await find_real_policy(session, UUID(sys.argv[1]) if len(sys.argv) > 1 else None)
        document = await session.get(Document, policy.source_document_id)
        fields = await load_fields(session, policy.id)
    await engine.dispose()

    extracted = [f for f in fields if f.value is not None]
    not_extracted = [f.name for f in fields if f.value is None]
    passed, failures = [], []
    async with create_storage(settings).open_to_tempfile(document.storage_path) as pdf_path:
        pdf = pdfium.PdfDocument(pdf_path)
        for field in extracted:
            provenance = field.provenance or {}
            page, bbox = provenance.get("page"), provenance.get("bbox")
            if page is None or bbox is None:
                failures.append((field, None, "no page or bbox stored"))
                continue
            text = text_in_bbox(pdf, page, bbox)
            if contains(text, field):
                passed.append(field)
            else:
                failures.append((field, page, f"not in the highlight{why_not(text, field)}, which reads: {normalise(text)[:140]!r}"))
        pdf.close()

    print(f"Policy {policy.id} ({policy.product_name or 'no product name'}), document {document.file_name}")
    print(f"Fields not extracted (no value, so nothing to check): {len(not_extracted)}" + (f": {', '.join(not_extracted)}" if not_extracted else ""))
    print()
    print(f"Fields checked:                       {len(extracted)}")
    print(f"Fields whose highlight has the value: {len(passed)}")
    print(f"Provenance survival rate:             {len(passed)} of {len(extracted)} ({len(passed) / len(extracted):.0%})")
    print()
    print("Contained:")
    for field in passed:
        print(f"  p{field.provenance['page']:>3}  {field.name} = {field.value}")
    print("Failures:")
    for field, page, why in failures:
        print(f"  {'p' + str(page) if page else ' - ':>4}  {field.name} = {str(field.value)[:60]}: {why}")
    if not failures:
        print("  none")
    print()
    print("n is one real policy. This checks that each highlight contains its value, not that the value is the right one.")


if __name__ == "__main__":
    asyncio.run(main())
