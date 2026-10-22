"""Seed the four eligibility demo claims on the real Star policy, plus the SYNTHETIC TEST FIXTURE policy.

THE CLAIMS are on the dev household's real uploaded policy (the Star
Comprehensive wording; app/qa/demo_policy.find_real_policy), not on the
fixture, so the demo's verdicts rest on a real policy's extracted terms.

The Star wording has no schedule page, so it states no policy dates (D-25).
They are entered here as user-supplied values, through the same validation as
PATCH /policies/{id} (D-39), and only if the policy has no dates yet:

    start 1 Jan 2026, end 31 Dec 2026, continuous cover since 1 Nov 2024

These are demo values, not facts about any real person's policy. Waiting
periods count from the first inception date (D-39).

Claim facts go through the same code as PUT /claims/{id}/facts (D-37). Claims
seeded earlier on the fixture are moved to the Star policy (the claim row is
updated; its event log, which is append-only, is unchanged).

    Claim               Band                       Why (waiting clock from 1 Nov 2024)
    Vikram, emergency   likely_eligible            appendicitis, not pre-existing, nothing listed applies
    Ananya, planned     at_risk                    knee arthroscopy is on the 24-month list (p30), which
                                                   ends 1 Nov 2026; admitted 1 Sep 2026. The period was
                                                   extracted at medium confidence, so: at risk
    Lakshmi, planned    likely_ineligible          pre-existing diabetes, admitted 2 Apr 2026; the 36-month
                        (at_risk until confirmed)  PED period (p31) ends 1 Nov 2027. Only a HIGH-confidence
                                                   failure is likely_ineligible (D-36): it becomes so once a
                                                   person confirms waiting period #3 on the policy screen.
                                                   This script deliberately does not confirm it.
    Ishaan, emergency   insufficient_information   whether the illness is pre-existing is not answered

THE FIXTURE (below) is kept for tests of the clause viewer and Q&A scripts.

Fixture: SYNTHETIC. Claude wrote this policy by hand: a fictional insurer ("Kavach"),
a generated 3-page schedule, 14 printed lines plus a title (15 clauses). It
exists so the eligibility bands and the clause viewer can be tested with known
numbers. It is NOT a real policy: keep it out of the demo and out of any
headline metric (Q&A latency, retrieval quality). The Q&A evaluation target is
the real Star Comprehensive wording (eval/qa_star_comprehensive.yaml).

For the web app and the Android developer: open each claim's Eligibility
tab and see a different verdict, each with its arithmetic and its clause.

Run from apps/api, after `alembic upgrade head` and `scripts/seed.py`:
    ../../.venv/bin/python scripts/seed_demo_claims.py

Safe to run again: the policy is found by its policy number and each claim
by its fixed id, and nothing that already exists is written twice.

Writes to the database in DATABASE_URL. Claims cannot be deleted afterwards:
the claim event log is append-only (the database refuses).

The demo policy has a small generated PDF schedule, stored with the local
storage backend, so every provenance link opens a real page and highlights
the line the value came from. All names are fictional.

The schedule's lines are also stored as clauses (document_chunk), one per
printed line with its real bbox, so the demo policy can answer questions. They
are embedded by scripts/index_chunks.py, which needs the Q&A models.

If the dev household has not chosen a city tier, it is set to "metro" so the
room-rent alert can be seen (Rs 5,000 cap below the unverified Rs 6,000
estimate). A tier the household already chose is left alone.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.claims.deadlines import india_date  # noqa: E402
from app.claims.facts import save_facts  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.ids import new_id  # noqa: E402
from app.db.models import (  # noqa: E402
    Claim, ClaimEvent, Document, DocumentChunk, Household, Member, Policy, policy_member,
)
# The table models, aliased: contracts.models has engine types with the same names.
from app.db.models import CoverageProfile as CoverageProfileRow  # noqa: E402
from app.db.models import Exclusion as ExclusionRow  # noqa: E402
from app.db.models import SubLimit as SubLimitRow  # noqa: E402
from app.db.models import WaitingPeriod as WaitingPeriodRow  # noqa: E402
from app.db.session import create_engine, create_session_factory  # noqa: E402
from app.qa.demo_policy import find_real_policy  # noqa: E402
from app.schemas.claims import ClaimFacts  # noqa: E402
from app.schemas.policies import PolicyUpdate  # noqa: E402
from app.services.policy_update import apply_policy_update  # noqa: E402
from app.services.policy_writer import store_extraction  # noqa: E402
from app.storage.base import build_object_path  # noqa: E402
from app.storage.factory import create_storage  # noqa: E402
from contracts.models import CoverageProfile, Extracted, ExtractionResult, Provenance, SubLimit, WaitingPeriod  # noqa: E402

INDIA = ZoneInfo("Asia/Kolkata")
HOUSEHOLD_ID = UUID("01920000-0000-7000-8000-000000000001")  # from scripts/seed.py
INSURER_ID = UUID("01920000-0000-7000-8000-000000000021")  # Kavach Health Assurance (fictional), from scripts/seed.py
MEMBER = {
    "Ananya": UUID("01920000-0000-7000-8000-000000000011"),
    "Vikram": UUID("01920000-0000-7000-8000-000000000012"),
    "Ishaan": UUID("01920000-0000-7000-8000-000000000013"),
    "Lakshmi": UUID("01920000-0000-7000-8000-000000000014"),
    # Added for the wrongful-denial demo (Phase 7). A fictional member, created here if missing.
    "Rajan": UUID("01920000-0000-7000-8000-000000000015"),
}
POLICY_NUMBER = "KHA/FAM/2024/DEMO-0001"
# Shown wherever the policy appears, so nobody mistakes it for a real one.
PRODUCT_NAME = "Kavach Family Health Plan (synthetic test fixture)"
DOCUMENT_ID = UUID("01920000-0000-7000-8000-0000000000e1")
FILE_NAME = "demo-policy-schedule.pdf"

# --- a small schedule PDF, with the position of every line recorded ---

PAGE_WIDTH, PAGE_HEIGHT, FONT_SIZE, LEFT = 612, 792, 12, 72
# Each page: the lines printed on it, top to bottom.
PAGES = [
    [
        "KAVACH FAMILY HEALTH PLAN - POLICY SCHEDULE (DEMO, FICTIONAL INSURER)",
        f"Policy number: {POLICY_NUMBER}",
        "Policy period: 14 Mar 2024 to 13 Mar 2027",
        "Insured persons: Ananya Rao, Vikram Rao, Ishaan Rao, Lakshmi Rao",
        "Sum insured (family floater): Rs 5,00,000",
        "Co-payment: Nil",
    ],
    [
        "SECTION 3: SUB-LIMITS AND WAITING PERIODS",
        "Room rent: up to Rs 5,000 per day",
        "Initial waiting period: 1 month from the policy start date",
        "Pre-existing diseases: covered after 48 months of continuous coverage",
        "Cataract: covered after 24 months of continuous coverage",
    ],
    [
        "SECTION 4: EXCLUSIONS AND CLAIMS",
        "Cosmetic or aesthetic treatment is excluded",
        "Dental treatment is excluded unless needed because of an accident",
        "Claim intimation: within 24 hours of admission",
    ],
]


@dataclass(frozen=True)
class Line:
    page: int
    text: str
    bbox: tuple[float, float, float, float]  # normalised, top-left origin (D-23)


def _layout() -> list[Line]:
    lines = []
    for page_index, texts in enumerate(PAGES, start=1):
        for row, text in enumerate(texts):
            baseline = 720 - row * 30
            width = min(len(text) * FONT_SIZE * 0.52, PAGE_WIDTH - LEFT - 20)
            bbox = (
                LEFT / PAGE_WIDTH,
                (PAGE_HEIGHT - baseline - FONT_SIZE) / PAGE_HEIGHT,
                (LEFT + width) / PAGE_WIDTH,
                (PAGE_HEIGHT - baseline + 4) / PAGE_HEIGHT,
            )
            lines.append(Line(page=page_index, text=text, bbox=tuple(round(v, 4) for v in bbox)))
    return lines


def _pdf() -> bytes:
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>"]
    page_ids = [4 + 2 * i for i in range(len(PAGES))]
    objects.append(f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in page_ids)}] /Count {len(PAGES)} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for page_id, texts in zip(page_ids, PAGES):
        commands = " ".join(f"BT /F1 {FONT_SIZE} Tf {LEFT} {720 - row * 30} Td ({text}) Tj ET" for row, text in enumerate(texts))
        stream = commands.encode("latin-1")
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] /Contents {page_id + 1} 0 R "
            "/Resources << /Font << /F1 3 0 R >> >> >>".encode()
        )
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    body, offsets = b"%PDF-1.4\n", []
    for number, content in enumerate(objects, start=1):
        offsets.append(len(body))
        body += f"{number} 0 obj\n".encode() + content + b"\nendobj\n"
    xref = len(body)
    body += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    body += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    body += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return body


def _extraction() -> ExtractionResult:
    """What Engine A would return for the schedule, written by hand, provenance included."""
    placeholder = uuid4()
    lines = {line.text: line for line in _layout()}

    def field(value: object, text: str) -> Extracted:
        line = lines[text]
        return Extracted(value=value, confidence="high", provenance=Provenance(document_id=placeholder, page=line.page, bbox=line.bbox, snippet=line.text))

    def period(kind: str, months: int, text: str, applies_to: str | None = None) -> WaitingPeriod:
        return WaitingPeriod(kind=kind, months=field(float(months), text), applies_to=applies_to, starts_on=None, expires_on=None)

    profile = CoverageProfile(
        policy_id=uuid4(),
        sum_insured=field(50_000_000, "Sum insured (family floater): Rs 5,00,000"),
        co_pay_percent=field(0.0, "Co-payment: Nil"),
        sub_limits=[
            SubLimit(category="room_rent", label="Room rent", cap_amount=field(500_000, "Room rent: up to Rs 5,000 per day"), cap_basis="per_day", percent_value=None)
        ],
        waiting_periods=[
            period("initial", 1, "Initial waiting period: 1 month from the policy start date"),
            period("pre_existing", 48, "Pre-existing diseases: covered after 48 months of continuous coverage"),
            period("disease_specific", 24, "Cataract: covered after 24 months of continuous coverage", applies_to="cataract"),
        ],
        exclusions=[
            field("Cosmetic or aesthetic treatment", "Cosmetic or aesthetic treatment is excluded"),
            field("Dental treatment, unless needed because of an accident", "Dental treatment is excluded unless needed because of an accident"),
        ],
        intimation_deadline_hours=field(24.0, "Claim intimation: within 24 hours of admission"),
        extraction_completeness=1.0,
    )
    return ExtractionResult(page_count=len(PAGES), coverage_profile=profile, line_items=[], chunks=[], warnings=[])


# --- the four claims ---


def ist(day: date, hour: int = 10) -> datetime:
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=INDIA)


@dataclass(frozen=True)
class DemoClaim:
    id: UUID
    band: str
    member: str
    admission_type: str
    hospital: str
    admitted_on: date
    discharged_on: date | None
    claimed_amount: int
    facts: dict
    events: tuple[tuple[str, datetime, str], ...]
    # Which policy: "star" (the uploaded Star wording) or "renewed" (SAMPLE-0002, its demo copy with cover since 2021).
    policy: str = "star"


NONE_APPLY = {"matched_waiting_periods": [], "matched_exclusions": []}

# The Star policy's dates, as the user would type them from a schedule (D-39). Demo values.
STAR_DATES = PolicyUpdate(start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), first_inception_date=date(2024, 11, 1))
# What the user would type from the Star schedule (D-46). The number is a sample, not a real policy number.
STAR_IDENTITY = PolicyUpdate(
    insurer_name="Star Health and Allied Insurance Co. Ltd.", product_name="Star Comprehensive Insurance Policy", policy_number="SAMPLE-0001"
)
# Positions in the Star policy's waiting_periods, as GET /policies/{id} returns them:
# 0 initial, 1 disease_specific (the listed conditions, p30-31), 2 pre_existing, 3 maternity.
STAR_LISTED_CONDITIONS = 1

CLAIMS = (
    DemoClaim(
        UUID("01920000-0000-7000-8000-0000000000f1"), "likely_eligible", "Vikram", "emergency", "Navjeevan Multispeciality Hospital, Pune",
        date(2026, 8, 10), date(2026, 8, 13), 12_000_000,
        {"diagnosis": "Acute appendicitis", "condition_is_pre_existing": False, "first_diagnosed_on": date(2026, 8, 10), "planned_room_rent_per_day": 450_000, **NONE_APPLY},
        (("intimated", ist(date(2026, 8, 10), 11), "Called the insurer helpline on admission"),
         ("documents_submitted", ist(date(2026, 8, 16)), "Discharge summary, bill and receipts sent")),
    ),
    DemoClaim(
        UUID("01920000-0000-7000-8000-0000000000f2"), "at_risk", "Ananya", "planned", "Shubhankar Hospital, Pune",
        date(2026, 9, 1), date(2026, 9, 3), 9_500_000,
        {"diagnosis": "Planned knee arthroscopy", "condition_is_pre_existing": False, "first_diagnosed_on": date(2026, 7, 20), "planned_room_rent_per_day": 800_000,
         "matched_waiting_periods": [STAR_LISTED_CONDITIONS], "matched_exclusions": []},
        (("intimated", ist(date(2026, 8, 28)), "Pre-authorisation request sent before admission"),),
    ),
    DemoClaim(
        UUID("01920000-0000-7000-8000-0000000000f3"), "likely_ineligible", "Lakshmi", "planned", "Navjeevan Multispeciality Hospital, Pune",
        date(2026, 4, 2), date(2026, 4, 6), 18_500_000,
        {"diagnosis": "Complications of type 2 diabetes", "condition_is_pre_existing": True, "first_diagnosed_on": date(2023, 11, 5), "planned_room_rent_per_day": 400_000, **NONE_APPLY,
         "denial_ground": "ped_waiting_period"},  # the ground the denial gave, as the user would choose it (D-48)
        (("intimated", ist(date(2026, 3, 31)), "Planned admission notified in advance"),
         ("documents_submitted", ist(date(2026, 4, 8)), "Claim file submitted"),
         ("under_review", ist(date(2026, 4, 10)), "Insurer acknowledged"),
         ("denied", ist(date(2026, 5, 2), 15), "Denied as a pre-existing disease within the waiting period")),
    ),
    DemoClaim(
        UUID("01920000-0000-7000-8000-0000000000f4"), "insufficient_information", "Ishaan", "emergency", "Shubhankar Hospital, Pune",
        date(2026, 10, 1), date(2026, 10, 3), 6_000_000,
        {"diagnosis": "Severe asthma attack", "condition_is_pre_existing": None, "first_diagnosed_on": None, "planned_room_rent_per_day": 350_000,
         "matched_waiting_periods": None, "matched_exclusions": []},
        (("intimated", ist(date(2026, 10, 1), 22), "Told the insurer the same night"),),
    ),
    # The wrongful denial: a pre-existing condition, but admitted after the 36-month PED period
    # ended, counted from first inception (1 Jun 2021, so it ended 1 Jun 2024). Denied anyway.
    DemoClaim(
        UUID("01920000-0000-7000-8000-0000000000f5"), "likely_eligible", "Rajan", "planned", "Navjeevan Multispeciality Hospital, Pune",
        date(2026, 7, 14), date(2026, 7, 18), 24_000_000,
        {"diagnosis": "Hypertensive heart disease", "condition_is_pre_existing": True, "first_diagnosed_on": date(2019, 4, 10),
         "planned_room_rent_per_day": 400_000, **NONE_APPLY, "denial_ground": "ped_waiting_period"},
        (("intimated", ist(date(2026, 7, 10)), "Planned admission notified in advance"),
         ("documents_submitted", ist(date(2026, 7, 22)), "Claim file submitted"),
         ("under_review", ist(date(2026, 7, 25)), "Insurer acknowledged"),
         ("denied", ist(date(2026, 8, 20), 15), "Denied as a pre-existing disease within the waiting period")),
        policy="renewed",
    ),
)

# SAMPLE-0002: a demo copy of the Star policy (same wording document, a copy of its extracted terms)
# held since 2021 without a break. It exists only so a wrongful PED denial can be shown today: the
# Star policy's own cover started 1 Nov 2024, so its 36-month PED period has not ended yet.
# Its copied terms duplicate the Star policy's and are NOT extraction-accuracy data (DECISIONS.md).
RENEWED_POLICY_ID = UUID("01920000-0000-7000-8000-0000000000a2")
RENEWED = PolicyUpdate(
    insurer_name="Star Health and Allied Insurance Co. Ltd.", product_name="Star Comprehensive Insurance Policy", policy_number="SAMPLE-0002",
    start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), first_inception_date=date(2021, 6, 1),
)


async def seed_policy(session: AsyncSession, settings) -> UUID:
    existing = await session.scalar(select(Policy.id).where(Policy.policy_number == POLICY_NUMBER))
    if existing is not None:
        return existing

    storage = create_storage(settings)
    storage_path = build_object_path(HOUSEHOLD_ID, DOCUMENT_ID, FILE_NAME)
    content = _pdf()
    try:
        await storage.save(storage_path, content, "application/pdf")
    except Exception:  # noqa: BLE001 - already there from an earlier, interrupted run
        pass

    document = await session.get(Document, DOCUMENT_ID)
    if document is None:
        document = Document(
            id=DOCUMENT_ID, household_id=HOUSEHOLD_ID, file_name=FILE_NAME, mime_type="application/pdf",
            storage_path=storage_path, size_bytes=len(content), parse_status="parsed",
        )
        session.add(document)
        await session.flush()
    policy_id = await store_extraction(session, document, _extraction())
    assert policy_id is not None
    policy = await session.get(Policy, policy_id)
    policy.insurer_id = INSURER_ID
    policy.policy_number = POLICY_NUMBER
    policy.product_name = PRODUCT_NAME
    policy.policy_type = "family_floater"
    policy.start_date = date(2024, 3, 14)
    policy.end_date = date(2027, 3, 13)
    for member_id in MEMBER.values():
        await session.execute(policy_member.insert().values(policy_id=policy_id, member_id=member_id))
    return policy_id


async def seed_chunks(session: AsyncSession) -> int:
    """One clause per printed line of the schedule, if the document has none yet. Returns how many were written."""
    existing = await session.scalar(select(DocumentChunk.id).where(DocumentChunk.document_id == DOCUMENT_ID).limit(1))
    if existing is not None:
        return 0
    lines = _layout()
    session.add_all(
        DocumentChunk(id=new_id(), document_id=DOCUMENT_ID, position=position, page=line.page, text=line.text, bbox=list(line.bbox))
        for position, line in enumerate(lines)
    )
    return len(lines)


async def seed_star_dates(session: AsyncSession, star: Policy) -> str:
    """Enter the Star policy's dates (D-39), unless the user has already entered any."""
    if (star.start_date, star.end_date, star.first_inception_date) == (STAR_DATES.start_date, STAR_DATES.end_date, STAR_DATES.first_inception_date):
        return "already entered"
    if any((star.start_date, star.end_date, star.first_inception_date)):
        return "left alone: different dates were already entered, so the bands below may differ"
    apply_policy_update(star, STAR_DATES, india_date(datetime.now(INDIA)))
    await session.commit()
    return "entered now"


async def seed_star_identity(session: AsyncSession, star: Policy) -> str:
    """Enter the Star policy's insurer, product and number (D-46) through the PATCH code, unless any is already set."""
    current = (star.insurer_name, star.product_name, star.policy_number)
    wanted = (STAR_IDENTITY.insurer_name, STAR_IDENTITY.product_name, STAR_IDENTITY.policy_number)
    if current == wanted:
        return "already entered"
    if any(current):
        return f"left alone: already set to {current}"
    apply_policy_update(star, STAR_IDENTITY, india_date(datetime.now(INDIA)))
    await session.commit()
    return "entered now"


async def seed_renewed_policy(session: AsyncSession, star: Policy) -> str:
    """SAMPLE-0002 for Rajan: a copy of the Star policy's row and coverage terms, with its own dates (via the PATCH code)."""
    if await session.get(Policy, RENEWED_POLICY_ID) is not None:
        return "already there"
    if await session.get(Member, MEMBER["Rajan"]) is None:
        session.add(Member(id=MEMBER["Rajan"], household_id=HOUSEHOLD_ID, full_name="Rajan Rao", relationship="parent",
                           date_of_birth=date(1958, 3, 10)))
    renewed = Policy(id=RENEWED_POLICY_ID, household_id=HOUSEHOLD_ID, source_document_id=star.source_document_id,
                     policy_type=star.policy_type, user_entered_fields=[])
    session.add(renewed)
    await session.flush()
    await copy_coverage_terms(session, star.id, renewed.id)
    apply_policy_update(renewed, RENEWED, india_date(datetime.now(INDIA)))
    await session.execute(policy_member.insert().values(policy_id=renewed.id, member_id=MEMBER["Rajan"]))
    await session.commit()
    return "created"


def _copy_row(row: object, **changes: object) -> object:
    """A new row of the same table with every column copied, except a new id and the given changes."""
    table = type(row).__table__
    values = {column.key: getattr(row, column.key) for column in table.columns}
    return type(row)(**{**values, "id": new_id(), **changes})


async def copy_coverage_terms(session: AsyncSession, from_policy: UUID, to_policy: UUID) -> None:
    """Copy a policy's coverage profile and its three lists, values, provenance and user confirmations included."""
    profile = await session.scalar(select(CoverageProfileRow).where(CoverageProfileRow.policy_id == from_policy))
    if profile is None:
        raise SystemExit("The Star policy has no coverage profile to copy.")
    copied = _copy_row(profile, policy_id=to_policy)
    session.add(copied)
    await session.flush()
    for model in (SubLimitRow, WaitingPeriodRow, ExclusionRow):
        for row in await session.scalars(select(model).where(model.coverage_profile_id == profile.id)):
            session.add(_copy_row(row, coverage_profile_id=copied.id))
    await session.flush()


async def seed_claims(session: AsyncSession, star: Policy) -> list[str]:
    """Each demo claim on its policy, with its facts. Creates, moves or updates; never writes an event twice."""
    done = []
    today = india_date(datetime.now(INDIA))
    for demo in CLAIMS:
        policy_id = RENEWED_POLICY_ID if demo.policy == "renewed" else star.id
        claim = await session.get(Claim, demo.id)
        if claim is None:
            claim = Claim(
                id=demo.id, household_id=HOUSEHOLD_ID, policy_id=policy_id, member_id=MEMBER[demo.member],
                claim_type="reimbursement", admission_type=demo.admission_type, hospital_name=demo.hospital,
                admitted_on=demo.admitted_on, discharged_on=demo.discharged_on, claimed_amount=demo.claimed_amount,
            )
            session.add(claim)
            await session.flush()
            previous = None
            for seq, (state, occurred_at, note) in enumerate(demo.events, start=1):
                session.add(ClaimEvent(id=uuid4(), claim_id=demo.id, seq=seq, from_state=previous, to_state=state,
                                       occurred_at=occurred_at, note=note, source="user"))
                previous = state
            action = "created"
        elif claim.policy_id != policy_id:
            claim.policy_id = policy_id  # the claim row only; its events are append-only and stay as they are
            action = "moved to its policy"
        else:
            action = "facts updated"
        await session.flush()
        # The same checks and writes as PUT /claims/{id}/facts; it commits.
        await save_facts(session, claim, ClaimFacts(**demo.facts), today)
        done.append(f"{demo.member} -> {demo.band}: {action}")
    return done


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    factory = create_session_factory(engine)
    async with factory() as session, session.begin():
        # Rajan is created with his policy below; the others come from scripts/seed.py.
        missing = [name for name, member_id in MEMBER.items() if name != "Rajan" and await session.get(Member, member_id) is None]
        if missing:
            raise SystemExit(f"Run scripts/seed.py first: members missing: {missing}")
        policy_id = await seed_policy(session, settings)
        chunks = await seed_chunks(session)
        # Rows seeded before the fixture was labelled get the label too.
        fixture = await session.get(Policy, policy_id)
        if fixture is not None and fixture.product_name != PRODUCT_NAME:
            fixture.product_name = PRODUCT_NAME
        household = await session.get(Household, HOUSEHOLD_ID)
        set_tier = household.city_tier is None
        if set_tier:
            household.city_tier = "metro"
        tier = household.city_tier
    # The claims: their own session, because the facts code commits as it goes.
    async with factory() as session:
        star = await find_real_policy(session)
        dates = await seed_star_dates(session, star)
        identity = await seed_star_identity(session, star)
        renewed = await seed_renewed_policy(session, star)
        claims = await seed_claims(session, star)
    await engine.dispose()
    print(f"Fixture policy {policy_id} ({POLICY_NUMBER}); clauses: {chunks} written" + (" (run scripts/index_chunks.py)" if chunks else ""))
    print(f"Household city tier: {tier}" + (" (set now)" if set_tier else " (already chosen; left alone)"))
    print(f"Demo claims are on the Star policy {star.id}. Its dates: {dates}. Its insurer, product and number: {identity}.")
    print(f"SAMPLE-0002 (demo copy of the Star policy, cover since 1 Jun 2021) for Rajan's claim: {renewed}.")
    for line in claims:
        print(f"  {line}")
    print("Lakshmi's claim is at_risk until a person confirms waiting period #3 (36 months, p31) on the policy screen.")


if __name__ == "__main__":
    asyncio.run(main())
