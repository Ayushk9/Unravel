"""Grievance drafting without a database: rungs, the deterministic letter, evidence, verification, the award ceiling.

The pipeline tests stub retrieval (so no database) and use FakeGrievanceLlm
(so no Gemini). They prove the parts the brief makes non-negotiable: the
header never comes from the model, an unsupported paragraph is kept and
flagged, and the Ombudsman award ceiling never reaches any output.
"""

from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from app.claims.completeness import AttachedDocument, compute_completeness
from app.claims.deadlines import ClaimFacts, EventFact, compute_deadlines
from app.claims.rungs import UNVERIFIED_NOTE, RungContext, rung_options
from app.core.ids import new_id
from app.grievance import run_draft
from app.grievance.evidence import enclosures, evidence_checklist
from app.grievance.letter import (
    ASSESSMENT_AGREES,
    DISCLAIMER,
    TEMPLATE_PARAGRAPHS,
    NO_ARGUMENT_PLACEHOLDER,
    NOT_RECORDED,
    UNCONFIRMED_MARK,
    LetterFacts,
    header_lines,
    render_letter_text,
    subject,
    template_paragraphs,
)
from app.grievance.llm import GeneratedDraft, GeneratedParagraph
from app.grievance.run_draft import DraftContext, citation_precision, draft_letter, merge_clauses, search_queries
from app.qa.retrieval import Clause, Retrieved
from app.rules.loader import load_deadline_rules, load_grievance_rungs, load_ombudsman_rules, load_required_documents
from app.schemas.grievances import DraftParagraph
from engines.rules.models import CheckResult, MissingFact
from engines.rules.precedent import NOTE_MATCHED, NOTE_NO_MATCH, NOTE_NONE_LOADED
from tests.fake_models import FakeGrievanceLlm

IST = "+05:30"
CLAIM_ID = UUID("01920000-0000-7000-8000-0000000000f3")
TODAY = date(2026, 10, 20)
ROOM_RENT = "Room rent is limited to Rs 5,000 per day."
PED = "Pre-existing diseases are covered after 36 months of continuous coverage."


def at(day: str) -> datetime:
    return datetime.fromisoformat(f"{day}T10:00:00{IST}")


def context_for(state_path: list[tuple[str, str]], today: date = TODAY) -> RungContext:
    events = tuple(EventFact(seq=i, to_state=s, occurred_at=at(d)) for i, (s, d) in enumerate(state_path, start=1))
    facts = ClaimFacts(claim_id=CLAIM_ID, current_state=state_path[-1][0], admitted_on=date(2026, 4, 2), events=events)
    deadlines, _ = compute_deadlines(facts, 24.0, load_deadline_rules(), today)
    return RungContext(current_state=facts.current_state, events=events, deadlines=tuple(deadlines))


def options(state_path: list[tuple[str, str]], today: date = TODAY) -> dict[str, Any]:
    return {o.rung: o for o in rung_options(context_for(state_path, today), load_grievance_rungs())}


DENIED = [("intimated", "2026-04-02"), ("documents_submitted", "2026-04-10"), ("under_review", "2026-04-12"), ("denied", "2026-05-02")]


# --- rule files ---


def test_rule_files_load_and_every_rung_rule_is_unverified_with_no_invented_url() -> None:
    rungs = load_grievance_rungs()
    assert list(rungs.rungs) == ["insurer_grievance_cell", "irdai_bima_bharosa", "insurance_ombudsman"]
    assert all(not r.verified and r.source.url is None for r in rungs.rungs.values())
    ceiling = load_ombudsman_rules().award_ceiling
    # Verified by Ayush on 2026-10-23: Rs 50 lakh, Rule 17(3) proviso (ii), with the official URL.
    assert (ceiling.value, ceiling.verified) == (500_000_000, True) and ceiling.source.url.startswith("https://www.cioins.co.in/")


def test_no_number_in_any_sentence_of_the_rung_file() -> None:
    """Dates in reasons come from deadline rules ({due}, {event_date}); the rung file itself states no figure."""
    for rung in load_grievance_rungs().rungs.values():
        sentences = [rung.label, rung.addressee, rung.unavailable]
        sentences += [text for c in rung.when for text in (c.reason, c.reason_after_due) if text]
        assert not [text for text in sentences if re.search(r"\d", text)]


# --- rungs ---


def test_an_intimated_claim_has_no_rung_yet_and_says_when_it_will() -> None:
    result = options([("intimated", "2026-04-02")])
    assert not any(o.available for o in result.values())
    assert result["insurance_ombudsman"].reason.startswith("Available once")


def test_after_a_denial_every_rung_is_offered_with_its_reason_and_unverified_marking() -> None:
    result = options(DENIED)

    assert all(o.available and not o.verified for o in result.values())
    ombudsman = result["insurance_ombudsman"]
    assert "denied on 2 May 2026" in ombudsman.reason and "until 2 May 2027" in ombudsman.reason
    assert ombudsman.reason.endswith(UNVERIFIED_NOTE) and ombudsman.rule_ids == ["ombudsman_filing"]


def test_an_expired_ombudsman_window_is_still_offered_but_says_it_may_have_passed() -> None:
    ombudsman = options(DENIED, today=date(2027, 6, 1))["insurance_ombudsman"]
    assert ombudsman.available and "may have passed" in ombudsman.reason and "2 May 2027" in ombudsman.reason


def test_under_review_offers_the_grievance_cell_before_and_after_the_decision_date() -> None:
    path = [("intimated", "2026-04-02"), ("documents_submitted", "2026-04-10"), ("under_review", "2026-04-12")]
    early = options(path, today=date(2026, 4, 20))
    late = options(path, today=date(2026, 6, 1))

    assert early["insurer_grievance_cell"].available and "may be early" in early["insurer_grievance_cell"].reason
    assert "has passed" in late["insurer_grievance_cell"].reason
    assert not early["insurance_ombudsman"].available and not early["irdai_bima_bharosa"].available


def test_escalated_dates_the_ombudsman_from_the_grievance_event() -> None:
    result = options([*DENIED, ("escalated", "2026-05-10")], today=date(2026, 5, 20))
    assert "from 9 Jun 2026" in result["insurance_ombudsman"].reason
    assert result["insurance_ombudsman"].rule_ids == ["escalation_eligibility"]


# --- the deterministic letter ---


def letter_facts(**overrides: Any) -> LetterFacts:
    values = dict(
        rung="insurer_grievance_cell", addressee_template="Grievance Redressal Officer, {insurer}",
        insurer_name="Star Health and Allied Insurance", policy_number=None, product_name="Star Comprehensive",
        patient_name="Lakshmi Rao", hospital_name="Navjeevan Multispeciality Hospital, Pune",
        admitted_on=date(2026, 4, 2), discharged_on=date(2026, 4, 6), claimed_amount=18_500_000,
        denied_on=date(2026, 5, 2), denial_reason="Denied as a pre-existing disease within the waiting period",
    )
    return LetterFacts(**(values | overrides))


def test_header_comes_from_stored_facts_and_an_unrecorded_fact_is_null() -> None:
    lines = {line.label: line.value for line in header_lines(letter_facts())}
    assert lines["Amount claimed"] == "₹1,85,000"
    assert lines["Admitted on"] == "2 Apr 2026" and lines["Claim denied on"] == "2 May 2026"
    assert lines["Policy number"] is None, "never a placeholder that looks real"
    assert lines["Reason for denial, as recorded"] == "“Denied as a pre-existing disease within the waiting period”"
    assert subject(letter_facts()) == "Request to review the denial of a health insurance claim: Lakshmi Rao, policy number not recorded"


def test_letter_text_marks_unconfirmed_paragraphs_and_cites_pages_from_citations() -> None:
    from app.schemas.questions import Citation
    from contracts.models import Provenance

    citation = Citation(id="k1", kind="policy_clause", label="Page 31", external_url=None,
                        provenance=Provenance(document_id=new_id(), page=31, bbox=(0.1, 0.1, 0.5, 0.2), snippet="x"))
    paragraphs = [DraftParagraph(text="Confirmed.", citation_ids=["k1"], verified=True, source="model"),
                  DraftParagraph(text="Not confirmed.", citation_ids=["k1"], verified=False, source="model")]

    text = render_letter_text(letter_facts(), paragraphs, [citation], "CLOSING")

    assert "Confirmed. (Policy document, page 31)" in text
    assert f"{UNCONFIRMED_MARK}\nNot confirmed. (Policy document, page 31)" in text
    assert f"Policy number: {NOT_RECORDED}" in text and text.endswith(DISCLAIMER)


def test_a_letter_with_no_paragraphs_asks_the_user_to_write_their_own() -> None:
    assert NO_ARGUMENT_PLACEHOLDER in render_letter_text(letter_facts(), [], [], "CLOSING")


@pytest.mark.parametrize(("flags", "expected"), [([], 0.0), ([True, True, False], 2 / 3), ([True, True, True], 1.0), ([False], 0.0)])
def test_citation_precision_is_verified_over_all(flags: list[bool], expected: float) -> None:
    paragraphs = [DraftParagraph(text="p", citation_ids=["c"], verified=v, source="model") for v in flags]
    paragraphs += template_paragraphs()  # never counted (D-47)
    assert citation_precision(paragraphs) == pytest.approx(expected)


# --- evidence ---


def check(check_id: str, status: str, resolving: str | None = None) -> CheckResult:
    facts = (MissingFact(fact="f", where_to_get="w", resolving_document=resolving),) if resolving else ()
    return CheckResult(id=check_id, title=check_id.replace("_", " "), critical=True, status=status, confidence="high",
                       values={}, explanation="", governing_clause=None, missing_facts=facts)


def test_evidence_checklist_is_completeness_plus_the_denial_letter_plus_resolving_documents() -> None:
    attached = [AttachedDocument("discharge_summary", "high", False), AttachedDocument("denial_letter", "high", False)]
    report = compute_completeness(CLAIM_ID, "reimbursement", "planned", attached, load_required_documents())

    items = evidence_checklist(report, was_denied=True, checks=[check("ped_waiting_period", "unknown", "investigation_report"),
                                                                check("x", "unknown", "policy_schedule")])

    as_dict = {i.item: i.satisfied for i in items}
    assert as_dict["Discharge summary attached"] is True
    assert as_dict["Itemised hospital bill attached"] is False
    assert as_dict["Insurer's denial letter attached"] is True
    assert as_dict["Policy schedule attached"] is False
    assert list(as_dict).count("Investigation reports attached") == 1, "listed once though it is required and resolving"
    assert enclosures(items) == ["Discharge summary", "Insurer's denial letter"]


# --- retrieval helpers ---


def clause(text: str) -> Clause:
    return Clause(id=new_id(), page=9, position=0, text=text, bbox=[0.1, 0.1, 0.5, 0.2])


def test_search_queries_use_the_denial_reason_then_failed_and_at_risk_checks() -> None:
    checks = (check("ped_waiting_period", "failed"), check("room_rent_sub_limit", "at_risk"), check("claim_intimation", "satisfied"))
    assert search_queries("  PED denial  ", checks) == ["PED denial", "ped waiting period", "room rent sub limit"]
    assert search_queries(None, ()) == [run_draft.FALLBACK_QUERY]


def test_merge_clauses_round_robins_without_repeats_up_to_the_limit() -> None:
    a, b, c, d = clause("a"), clause("b"), clause("c"), clause("d")
    assert merge_clauses([[a, b, c], [b, d]], limit=3) == [a, b, d]


# --- the pipeline, with retrieval stubbed and a fake Gemini ---


@pytest.fixture
def clauses(monkeypatch: pytest.MonkeyPatch) -> list[Clause]:
    found = [clause(PED), clause(ROOM_RENT)]

    async def retrieve(*_: Any, **__: Any) -> Retrieved:
        return Retrieved(clauses=found)

    monkeypatch.setattr(run_draft, "retrieve", retrieve)
    return found


@asynccontextmanager
async def no_session():  # type: ignore[no-untyped-def]
    yield None


def draft_context(
    rung: str = "insurer_grievance_cell", band: str = "at_risk", checks: tuple[CheckResult, ...] | None = None,
    denial_ground: str | None = None, **letter: Any,
) -> DraftContext:
    """`band` defaults to one where our rules do not agree with the denial, so templates appear only when nothing survives."""
    rungs = load_grievance_rungs()
    return DraftContext(
        household_id=new_id(), claim_id=CLAIM_ID, rung=rung, document_id=new_id(),
        letter=letter_facts(rung=rung, addressee_template=rungs.rungs[rung].addressee, **letter),
        checks=checks if checks is not None else (check("ped_waiting_period", "failed"),), band=band, denial_ground=denial_ground,
        diagnosis="Complications of type 2 diabetes", current_state="denied",
        evidence=[],
    )


def draft(llm: FakeGrievanceLlm, context: DraftContext | None = None):  # type: ignore[no-untyped-def]
    return asyncio.run(draft_letter(session_factory=no_session, models=None, llm=llm, context=context or draft_context(),  # type: ignore[arg-type]
                                    now=datetime(2026, 10, 20, tzinfo=timezone.utc))).result


def test_the_header_never_comes_from_the_model(clauses: list[Clause]) -> None:
    hostile = GeneratedDraft(abstain=False, paragraphs=[GeneratedParagraph(
        text="Policy number FAKE-999. I claimed Rs 99,99,999 and was denied on 1 Jan 2020. Subject: refund now.", chunk_ids=["c1"])])
    context = draft_context()

    result = draft(FakeGrievanceLlm(draft=lambda *_: hostile), context)

    assert result.header_lines == header_lines(context.letter)
    assert result.subject == subject(context.letter) and result.addressee == "Grievance Redressal Officer, Star Health and Allied Insurance"
    header_text = " ".join(f"{h.label} {h.value}" for h in result.header_lines) + result.subject + result.addressee + result.closing
    assert "FAKE-999" not in header_text and "99,99,999" not in header_text
    assert result.paragraphs[0].verified is False, "its numbers are in no clause"


def test_an_unsupported_paragraph_is_kept_with_verified_false(clauses: list[Clause]) -> None:
    two = GeneratedDraft(abstain=False, paragraphs=[
        GeneratedParagraph(text=f"My policy says: {PED}", chunk_ids=["c1"]),
        GeneratedParagraph(text="My policy says room rent is not limited.", chunk_ids=["c2"]),
    ])
    llm = FakeGrievanceLlm(draft=lambda *_: two, judge=lambda pairs: ["not limited" not in text for text, _ in pairs])

    result = draft(llm)

    assert [p.verified for p in result.paragraphs] == [True, False]
    assert result.paragraphs[1].text == "My policy says room rent is not limited.", "kept, word for word"
    assert result.paragraphs[1].citation_ids == [str(clauses[1].id)], "keeps its citation so the user can check it"
    assert result.citation_precision == pytest.approx(0.5)
    assert UNCONFIRMED_MARK in result.letter_text and result.missing_context is None
    assert [c.id for c in result.citations] == [str(clauses[0].id), str(clauses[1].id)]
    assert all(c.kind == "policy_clause" and c.provenance.page == 9 for c in result.citations)


def test_a_paragraph_failing_the_number_check_is_never_sent_to_the_judge(clauses: list[Clause]) -> None:
    bad = GeneratedDraft(abstain=False, paragraphs=[GeneratedParagraph(text="Room rent is limited to Rs 9,000 per day.", chunk_ids=["c2"])])
    judged: list[int] = []
    llm = FakeGrievanceLlm(draft=lambda *_: bad, judge=lambda pairs: judged.append(len(pairs)) or [True] * len(pairs))

    result = draft(llm)

    assert result.paragraphs[0].verified is False and judged == [0]


def test_a_model_abstention_gives_our_own_sentence_and_still_a_letter(clauses: list[Clause]) -> None:
    result = draft(FakeGrievanceLlm(draft=lambda *_: GeneratedDraft(abstain=True, reason="the model's own words")))

    assert [p.source for p in result.paragraphs] == ["template"] * 3, "no model paragraph, so the fixed requests"
    assert result.citation_precision == 0.0
    assert result.missing_context == run_draft.NOT_DRAFTED and "model's own words" not in result.model_dump_json()
    assert result.header_lines and TEMPLATE_PARAGRAPHS[0] in result.letter_text


def test_no_clauses_found_is_an_abstention_with_no_model_call(monkeypatch: pytest.MonkeyPatch) -> None:
    async def retrieve(*_: Any, **__: Any) -> Retrieved:
        return Retrieved(clauses=[])

    monkeypatch.setattr(run_draft, "retrieve", retrieve)
    llm = FakeGrievanceLlm()

    result = draft(llm)

    assert result.missing_context == run_draft.NO_CLAUSES and llm.calls == []


def test_drafts_are_not_cached(clauses: list[Clause]) -> None:
    llm = FakeGrievanceLlm()
    first, second = draft(llm), draft(llm)
    assert llm.calls == ["draft", "judge", "draft", "judge"] and first.id != second.id


# --- the Ombudsman award ceiling: only in the Ombudsman rung, only as a limit, never in a letter ---

CEILING_WORDS = re.compile(r"lakh|ceiling|award limit|maximum (award|amount)|30,00,000|50,00,000|award at most", re.IGNORECASE)
LIMIT = load_ombudsman_rules().award_ceiling.shown_sentence()


@pytest.mark.parametrize("rung", ["insurer_grievance_cell", "irdai_bima_bharosa", "insurance_ombudsman"])
def test_the_award_ceiling_never_appears_in_a_letter(clauses: list[Clause], rung: str) -> None:
    result = draft(FakeGrievanceLlm(), draft_context(rung=rung, claimed_amount=None))
    assert not CEILING_WORDS.search(result.model_dump_json())


def test_the_award_ceiling_appears_only_in_the_offered_ombudsman_rung_worded_as_a_limit() -> None:
    assert LIMIT == ("By the Insurance Ombudsman Rules, the Ombudsman can award at most ₹50,00,000, including relevant expenses. "
                     "This is a limit on what can be awarded, not an amount you can expect.")
    for path in ([("intimated", "2026-04-02")], DENIED, [*DENIED, ("escalated", "2026-05-10")]):
        for option in rung_options(context_for(path), load_grievance_rungs(), LIMIT):
            shown = bool(CEILING_WORDS.search(option.reason))
            assert shown == (option.rung == "insurance_ombudsman" and option.available), (path[-1], option.rung)
    for note in (NOTE_NONE_LOADED, NOTE_NO_MATCH, NOTE_MATCHED):
        assert not CEILING_WORDS.search(note)


def test_an_unverified_ceiling_is_never_shown() -> None:
    from app.rules.loader import AwardCeiling

    unverified = AwardCeiling.model_validate({"value": 500_000_000, "verified": False, "rung_sentence": "at most {ceiling}",
                                             "source": {"document": "d", "section": None, "url": None}})
    assert unverified.shown_sentence() is None
    for option in rung_options(context_for(DENIED), load_grievance_rungs(), unverified.shown_sentence()):
        assert not CEILING_WORDS.search(option.reason)


def test_only_the_loader_and_the_rung_route_read_the_award_ceiling() -> None:
    app_dir = Path(__file__).resolve().parents[1] / "app"
    readers = sorted(p.relative_to(app_dir).as_posix() for p in app_dir.rglob("*.py") if "award_ceiling" in p.read_text(encoding="utf-8"))
    assert readers == ["api/v1/grievances.py", "rules/loader.py"]


# --- the addressee never carries contact details ---

CONTACT_DETAILS = re.compile(r"@|\+?\d[\d\s-]{7,}\d|\b(road|street|floor|nagar|marg|pin|pincode|tel|phone|email)\b", re.IGNORECASE)


@pytest.mark.parametrize("insurer", ["Star Health and Allied Insurance Co. Ltd.", None])
def test_the_addressee_is_exactly_the_officer_and_the_insurer_with_no_contact_details(insurer: str | None) -> None:
    from app.grievance.letter import addressee

    template = load_grievance_rungs().rungs["insurer_grievance_cell"].addressee
    facts = letter_facts(addressee_template=template, insurer_name=insurer)

    assert addressee(facts) == f"Grievance Redressal Officer, {insurer or 'your insurer'}"
    assert not CONTACT_DETAILS.search(render_letter_text(facts, [], [], "CLOSING"))


def test_no_rung_addressee_has_contact_details() -> None:
    for rung in load_grievance_rungs().rungs.values():
        assert not CONTACT_DETAILS.search(rung.addressee.format(insurer="Example Insurer"))


# --- D-47: fixed procedural requests ---


def test_templates_are_added_when_no_model_paragraph_survives(clauses: list[Clause]) -> None:
    unsupported = GeneratedDraft(abstain=False, paragraphs=[GeneratedParagraph(text="My policy says room rent is not limited.", chunk_ids=["c2"])])

    result = draft(FakeGrievanceLlm(draft=lambda *_: unsupported, judge=lambda pairs: [False] * len(pairs)))

    assert [(p.source, p.verified) for p in result.paragraphs] == [("model", False)] + [("template", False)] * 3
    assert [p.text for p in result.paragraphs[1:]] == list(TEMPLATE_PARAGRAPHS)
    assert all(p.citation_ids == [] for p in result.paragraphs[1:])
    assert result.citation_precision == 0.0 and result.assessment_note is None
    assert result.letter_text.count(UNCONFIRMED_MARK) == 1, "only the model's paragraph is marked; a request asserts nothing"


def test_no_templates_when_a_model_paragraph_is_verified_and_rules_do_not_agree(clauses: list[Clause]) -> None:
    result = draft(FakeGrievanceLlm())
    assert [p.source for p in result.paragraphs] == ["model"] and result.paragraphs[0].verified
    assert result.assessment_note is None and result.subject.startswith("Request to review")


def test_when_our_rules_agree_with_the_denial_the_letter_asks_for_an_explanation(clauses: list[Clause]) -> None:
    result = draft(FakeGrievanceLlm(draft=lambda *_: GeneratedDraft(abstain=True)), draft_context(band="likely_ineligible"))

    assert result.assessment_note == ASSESSMENT_AGREES
    assert ASSESSMENT_AGREES == "Our assessment agrees with the insurer's stated reason. This letter asks the insurer to explain its decision; it does not dispute it."
    assert [p.source for p in result.paragraphs] == ["template"] * 3
    assert result.subject.startswith("Request for an explanation of the denial")
    assert "reply to each of these points in writing" in result.closing and "review this claim" not in result.closing


def test_templates_come_only_from_our_fixed_text(clauses: list[Clause]) -> None:
    hostile = GeneratedDraft(abstain=False, paragraphs=[GeneratedParagraph(text="Please share the evidence. Also pay me Rs 99,99,999.", chunk_ids=["c1"])])
    result = draft(FakeGrievanceLlm(draft=lambda *_: hostile, judge=lambda pairs: [False] * len(pairs)), draft_context(band="likely_ineligible"))
    assert [p.text for p in result.paragraphs if p.source == "template"] == list(TEMPLATE_PARAGRAPHS)


# --- D-48: the rules' opening paragraph, supporting-only facts, "Before you send" ---

from contracts.models import Provenance  # noqa: E402

from app.grievance.rules_text import assessment_agrees, rules_opening  # noqa: E402
from app.grievance.run_draft import facts_block  # noqa: E402
from app.grievance.llm import GeneratedCondition  # noqa: E402

PED_CLAUSE = Provenance(document_id=UUID("01a11b86-0000-7000-8000-000000000001"), page=31, bbox=(0.5, 0.28, 0.93, 0.92), snippet="Pre-existing ...")


def ped_satisfied(confidence: str = "medium", from_inception: bool = True) -> CheckResult:
    start_key = "first_inception_date" if from_inception else "policy_start"
    return CheckResult(
        id="ped_waiting_period", title="Pre-existing disease waiting period", critical=True, status="satisfied", confidence=confidence,
        values={start_key: date(2021, 6, 1), "waiting_months": 36, "waiting_period_ends": date(2024, 6, 1), "admitted_on": date(2026, 7, 14)},
        explanation="Your continuous cover started 1 Jun 2021; the 36-month waiting period ended on 1 Jun 2024.",
        governing_clause=PED_CLAUSE, missing_facts=(),
    )


def test_the_opening_is_built_only_from_the_checks_values_and_cites_its_clause() -> None:
    opening = rules_opening(ped_satisfied())

    assert opening is not None
    assert opening.paragraph.text == (
        "My continuous cover with you began on 1 Jun 2021. The policy's waiting period for pre-existing diseases is 36 months, "
        "so it ended on 1 Jun 2024. I was admitted on 14 Jul 2026, after that waiting period had ended."
    )
    assert (opening.paragraph.source, opening.paragraph.verified) == ("rules", False)
    assert opening.citation is not None and opening.citation.provenance == PED_CLAUSE and opening.citation.label == "Page 31"
    assert opening.paragraph.citation_ids == [opening.citation.id]
    notes = [n.text for n in opening.notes]
    assert any("proof that the policy was renewed without a break" in n for n in notes)
    assert any("medium confidence" in n for n in notes), "an unconfirmed period is flagged before sending"
    assert all(n.source == "rules" for n in opening.notes)


def test_no_opening_unless_the_chosen_grounds_waiting_period_is_satisfied() -> None:
    failed = ped_satisfied().model_copy(update={"status": "failed"})
    other = CheckResult(id="room_rent_sub_limit", title="Room rent", critical=False, status="satisfied", confidence="high",
                        values={}, explanation="", governing_clause=None, missing_facts=())
    partial = ped_satisfied().model_copy(update={"values": {"waiting_months": 36}})
    assert rules_opening(None) is None and rules_opening(failed) is None
    assert rules_opening(other) is None, "only date-counted waiting periods have a fixed paragraph"
    assert rules_opening(partial) is None, "a missing value means no paragraph, never a guess"


def test_agreement_follows_the_chosen_ground_when_there_is_one() -> None:
    assert assessment_agrees(ped_satisfied().model_copy(update={"status": "failed"}), "at_risk") is True
    assert assessment_agrees(ped_satisfied(), "likely_ineligible") is False, "the ground's check supports the policyholder"
    assert assessment_agrees(None, "likely_ineligible") is True, "no ground chosen: D-47's band rule"


def test_the_model_sees_only_checks_that_support_the_policyholder() -> None:
    context = draft_context(checks=(ped_satisfied(), check("room_rent_sub_limit", "failed")), denial_ground="ped_waiting_period")
    facts = facts_block(context, rules_opening(ped_satisfied()))
    assert "Pre-existing disease waiting period: Your continuous cover started 1 Jun 2021" in facts
    assert "room rent" not in facts.lower(), "a failed check is not a ground to argue from"
    assert "do not repeat it" in facts


def test_a_wrongful_denial_letter_opens_with_the_rules_then_the_model_and_keeps_conditions_out(clauses: list[Clause]) -> None:
    answer = GeneratedDraft(abstain=False, paragraphs=[GeneratedParagraph(text=f"My policy says: {PED}", chunk_ids=["c1"])],
                            conditions=[GeneratedCondition(text="Cover is subject to the disease having been declared.", chunk_ids=["c1"]),
                                        GeneratedCondition(text="Room rent is limited to Rs 5,000 per day.", chunk_ids=["c2"])])
    judge = lambda pairs: ["declared" not in text for text, _ in pairs]  # noqa: E731 - the first condition is unsupported
    context = draft_context(checks=(ped_satisfied(),), denial_ground="ped_waiting_period", band="likely_eligible")

    result = draft(FakeGrievanceLlm(draft=lambda *_: answer, judge=judge), context)

    assert [p.source for p in result.paragraphs] == ["rules", "model"], "no templates: an argument survived and the rules don't agree"
    assert result.citations[0].id == "rule-ped_waiting_period" and result.citations[0].provenance.page == 31
    assert result.citation_precision == 1.0, "only model paragraphs count"
    assert result.assessment_note is None
    notes = {(n.source, n.verified): n.text for n in result.before_you_send}
    assert notes[("model", False)] == "Cover is subject to the disease having been declared."
    assert notes[("model", True)] == "Room rent is limited to Rs 5,000 per day."
    assert "declared" not in result.letter_text and "renewed without a break" not in result.letter_text
    assert "My continuous cover with you began on 1 Jun 2021." in result.letter_text and "(Policy document, page 31)" in result.letter_text
    assert UNCONFIRMED_MARK not in result.letter_text


def test_the_denial_ground_choices_are_exactly_the_eligibility_check_ids() -> None:
    from typing import get_args

    from app.schemas.claims import DenialGround
    from engines.rules.registry import ELIGIBILITY_RULES

    assert set(get_args(DenialGround)) == {rule.id for rule in ELIGIBILITY_RULES}


def test_the_policy_wording_is_ticked_when_the_policy_document_is_uploaded() -> None:
    report = compute_completeness(CLAIM_ID, "reimbursement", "planned", [], load_required_documents())
    checks = [check("room_rent_sub_limit", "unknown", "policy_wording")]
    ticked = {i.item: i.satisfied for i in evidence_checklist(report, True, checks, policy_document_uploaded=True)}
    unticked = {i.item: i.satisfied for i in evidence_checklist(report, True, checks)}
    assert ticked["Policy wording attached"] is True and unticked["Policy wording attached"] is False


def test_every_script_that_picks_a_policy_excludes_the_demo_policies() -> None:
    """SAMPLE-0002's terms are copies of the Star policy's; no evaluation or metric may read them (DECISIONS.md)."""
    from app.qa.demo_policy import EXCLUDED_FROM_EVALUATION

    assert set(EXCLUDED_FROM_EVALUATION) == {"KHA/FAM/2024/DEMO-0001", "SAMPLE-0002"}
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    picks_policy = [p for p in scripts.glob("*.py") if "select(Policy" in p.read_text(encoding="utf-8") or "find_real_policy" in p.read_text(encoding="utf-8")]
    # The seed scripts create the demo policies; every other script must go through the exclusion.
    readers = [p for p in picks_policy if not p.name.startswith("seed")]
    assert readers, "the check found nothing to check"
    for path in readers:
        text = path.read_text(encoding="utf-8")
        assert "find_real_policy" in text or "EXCLUDED_FROM_EVALUATION" in text, f"{path.name} may pick a demo policy"



def test_a_rules_opening_with_a_model_abstention_is_not_reported_as_having_no_argument(clauses: list[Clause]) -> None:
    abstained = GeneratedDraft(abstain=True, conditions=[GeneratedCondition(text="Room rent is limited to Rs 5,000 per day.", chunk_ids=["c2"])])
    context = draft_context(checks=(ped_satisfied(),), denial_ground="ped_waiting_period", band="likely_eligible")

    result = draft(FakeGrievanceLlm(draft=lambda *_: abstained), context)

    assert [p.source for p in result.paragraphs] == ["rules"]
    assert result.missing_context is None, "the letter argues from the rules"
    assert [n.source for n in result.before_you_send] == ["rules", "rules", "model"] and result.before_you_send[-1].verified


# --- settled conditions are dropped (2026-10-23) ---


def initial_satisfied() -> CheckResult:
    return CheckResult(id="initial_waiting_period", title="Initial waiting period", critical=True, status="satisfied", confidence="medium",
                       values={}, explanation="", governing_clause=None, missing_facts=())


def test_a_condition_restating_a_satisfied_check_is_dropped_and_a_further_requirement_is_kept(clauses: list[Clause]) -> None:
    from app.grievance.run_draft import drop_settled_conditions

    thirty_days = GeneratedCondition(text="Treatment within 30 days of the first policy is excluded.", chunk_ids=["c1"],
                                     restates_check="initial_waiting_period")
    declared = GeneratedCondition(text="Cover is subject to the disease having been declared at application.", chunk_ids=["c1"],
                                  restates_check="none")
    ped_failed_restated = GeneratedCondition(text="Pre-existing diseases are covered after 36 months.", chunk_ids=["c1"],
                                             restates_check="ped_waiting_period")
    checks = (ped_satisfied().model_copy(update={"status": "failed"}), initial_satisfied())

    kept, dropped = drop_settled_conditions([thirty_days, declared, ped_failed_restated], checks)

    assert [c.text for c in kept] == [declared.text, ped_failed_restated.text], "only a SATISFIED check's restatement is settled"
    assert dropped == [{"text": thirty_days.text, "restates_check": "initial_waiting_period", "reason": "check already satisfied"}]


def test_settled_conditions_never_reach_before_you_send_or_the_judge(clauses: list[Clause]) -> None:
    answer = GeneratedDraft(abstain=True, conditions=[
        GeneratedCondition(text="Treatment within 30 days of the first policy is excluded.", chunk_ids=["c1"], restates_check="initial_waiting_period"),
        GeneratedCondition(text="Cover is subject to the disease having been declared at application.", chunk_ids=["c1"]),
    ])
    judged: list[str] = []
    judge = lambda pairs: [judged.append(text) or True for text, _ in pairs]  # noqa: E731
    context = draft_context(checks=(ped_satisfied(), initial_satisfied()), denial_ground="ped_waiting_period", band="likely_eligible")

    result = draft(FakeGrievanceLlm(draft=lambda *_: answer, judge=judge), context)

    model_notes = [n.text for n in result.before_you_send if n.source == "model"]
    assert model_notes == ["Cover is subject to the disease having been declared at application."]
    assert judged == ["Cover is subject to the disease having been declared at application."], "a dropped condition costs no judging"
