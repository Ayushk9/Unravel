"""The `generate_grievance_draft` job: one letter for one claim and one rung (D-43).

Stages, each written to job.progress:

    retrieving   load the claim and run the rules on it; search the policy's own
                 clauses with the denial reason and every failed or at-risk check
    drafting     Gemini writes the argument paragraphs, each citing clause ids, or abstains
    verifying    the number check, then the support judge, on every paragraph
    done

Who writes what:
  - code, from the database: subject, addressee, header (names, policy number,
    dates, amounts, denial date and recorded reason), the pages cited, the
    evidence checklist, the closing, the disclaimer and the plain-text letter;
  - the model: the text of the argument paragraphs, nothing else.

Unlike a Q&A answer, a paragraph that fails verification is KEPT and returned
with `verified: false` (product rule 4); the client must flag it. Drafts are
never cached: the claim's facts can change between attempts (D-42).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.claims.completeness import compute_completeness
from app.claims.deadlines import india_date
from app.claims.reader import find_claim_row, load_attached_documents
from app.core.ids import new_id
from app.db.models import ClaimEvent, Document, Job, Member, Policy
from app.db.models import GrievanceDraft as GrievanceDraftRow
from app.grievance.evidence import enclosures, evidence_checklist
from app.grievance.rules_text import RulesText, assessment_agrees, ground_check, rules_opening
from app.grievance.letter import (
    ASSESSMENT_AGREES,
    DISCLAIMER,
    LetterFacts,
    addressee,
    closing,
    header_lines,
    render_letter_text,
    subject,
    template_paragraphs,
)
from app.grievance.llm import GRIEVANCE_PROMPT_VERSION, RUNG_DESCRIPTIONS, GeneratedCondition, GrievanceLlm, generated_draft_problems
from app.jobs.parse_document import JobFailure
from app.jobs.queue import ClaimedJob, SessionFactory, set_progress
from app.models_server.client import Models, ModelServerError
from app.qa.llm import ClausePrompt, LlmError
from app.qa.retrieval import Clause, retrieve
from app.qa.run_question import Progress, clause_citation, no_progress
from app.rules.loader import load_grievance_rungs, load_required_documents
from app.rules_bridge import eligibility_input
from app.schemas.grievances import BeforeYouSendNote, DraftParagraph, EvidenceItem, GrievanceDraft
from app.schemas.questions import Citation
from engines.retrieval.verify import Removed, Sentence, precheck, verify_in_order
from engines.rules import assess_eligibility
from engines.rules.models import CheckResult

logger = logging.getLogger("unravel.grievance")

RETRIEVING = ("retrieving", 20)
DRAFTING = ("drafting", 50)
VERIFYING = ("verifying", 80)

MAX_CLAUSES = 6
# Used when the claim has no denial reason and no failed check to search with (a delay grievance).
FALLBACK_QUERY = "claim settlement procedure and time for the insurer to decide a claim"

# Our own sentences, never the model's (product rule 3: abstention is information, not an error).
NO_CLAUSES = (
    "We couldn't find clauses in your policy's text that bear on this claim, so the letter has no argument "
    "paragraphs. Add your own reasons where the letter says so. If your policy wording isn't uploaded, uploading it may help."
)
NOT_DRAFTED = (
    "The clauses we found in your policy's text don't give honest grounds to argue from, so the letter has no "
    "argument paragraphs. Add your own reasons where the letter says so. The relevant clause may be in a document "
    "you haven't uploaded, such as the full policy wording."
)

MODELS_UNAVAILABLE = "The search models aren't available right now. Please try again in a moment."
LLM_UNAVAILABLE = "We couldn't draft the letter right now. Please try again in a moment."
LLM_BUSY = "The drafting service is busy right now. Please try again in a minute."


@dataclass(frozen=True)
class DraftContext:
    """Everything loaded from the database before any model is called."""

    household_id: UUID
    claim_id: UUID
    rung: str
    document_id: UUID
    letter: LetterFacts
    checks: tuple[CheckResult, ...]
    # The eligibility band (D-36), used for D-47 when no denial ground was chosen.
    band: str
    # The insurer's denial ground as the user chose it: an eligibility check id, or None (D-48).
    denial_ground: str | None
    diagnosis: str | None
    current_state: str
    evidence: list[EvidenceItem]


@dataclass
class DraftOutcome:
    result: GrievanceDraft
    record: dict[str, Any]
    timings: dict[str, float]


def citation_precision(paragraphs: list[DraftParagraph]) -> float:
    """Verified model paragraphs / all model paragraphs. 0 when there are none. Template paragraphs don't count (D-47)."""
    written = [p for p in paragraphs if p.source == "model"]
    if not written:
        return 0.0
    return sum(1 for p in written if p.verified) / len(written)


def drop_settled_conditions(conditions: list[GeneratedCondition], checks: tuple[CheckResult, ...]) -> tuple[list[GeneratedCondition], list[dict[str, str]]]:
    """Drop a condition that restates a check our rules already found satisfied: it is settled, not a risk.

    Deterministic, given the model's `restates_check` tag (made in the same draft call; no extra call).
    A condition tagged "none" (a requirement no check evaluates) is always kept.
    """
    satisfied = {check.id for check in checks if check.status == "satisfied"}
    kept, dropped = [], []
    for condition in conditions:
        if condition.restates_check in satisfied:
            dropped.append({"text": condition.text, "restates_check": condition.restates_check, "reason": "check already satisfied"})
        else:
            kept.append(condition)
    return kept, dropped


def search_queries(denial_reason: str | None, checks: tuple[CheckResult, ...], denial_ground: str | None = None) -> list[str]:
    """What to search the policy for: the recorded denial reason, the chosen ground's check, then each failed or at-risk check."""
    queries = [denial_reason.strip()] if denial_reason and denial_reason.strip() else []
    ground = ground_check(checks, denial_ground)
    if ground is not None:
        queries.append(ground.title)
    queries += [check.title for check in checks if check.status in ("failed", "at_risk")]
    return list(dict.fromkeys(queries)) or [FALLBACK_QUERY]


def merge_clauses(per_query: list[list[Clause]], limit: int = MAX_CLAUSES) -> list[Clause]:
    """Round-robin over the queries' ranked lists, best first, without repeats, up to `limit`."""
    merged: list[Clause] = []
    seen: set[UUID] = set()
    for rank in range(max((len(c) for c in per_query), default=0)):
        for clauses in per_query:
            if rank < len(clauses) and clauses[rank].id not in seen and len(merged) < limit:
                seen.add(clauses[rank].id)
                merged.append(clauses[rank])
    return merged


def facts_block(context: DraftContext, opening: RulesText | None = None) -> str:
    """The claim facts the model may argue from, and the judge checks claim statements against. All from the database.

    Only the checks that SUPPORT the policyholder (satisfied) are given as grounds to argue
    from (D-48); a failed or unknown check is not something the letter may argue with.
    """
    lines = [f"Claim status: {context.current_state.replace('_', ' ')}"]
    if context.letter.denial_reason:
        lines.append(f"Reason for denial, as recorded by the policyholder: “{context.letter.denial_reason}”")
    if context.diagnosis:
        lines.append(f"Diagnosis, as entered by the policyholder: {context.diagnosis}")
    supporting = [c for c in context.checks if c.status == "satisfied" and c.id != "coverage_profile"]
    if supporting:
        lines.append("CHECKS THAT SUPPORT THE POLICYHOLDER (made by rules on the policyholder's documents):")
        lines += [f"- {c.title}: {c.explanation}" for c in supporting]
    else:
        lines.append("CHECKS THAT SUPPORT THE POLICYHOLDER: none.")
    if opening is not None:
        lines.append(f"The letter already opens with this paragraph (do not repeat it): {opening.paragraph.text}")
    return "\n".join(lines)


async def load_context(session_factory: SessionFactory, household_id: UUID, claim_id: UUID, rung: str, today: date) -> DraftContext:
    async with session_factory() as session:
        claim = await find_claim_row(session, household_id, claim_id)
        if claim is None:
            raise JobFailure("claim_missing", "This claim is no longer available.", retryable=False)
        policy = await session.scalar(
            select(Policy).where(Policy.id == claim.policy_id, Policy.household_id == household_id).options(joinedload(Policy.insurer))
        )
        document = await session.get(Document, policy.source_document_id) if policy and policy.source_document_id else None
        if policy is None or document is None or document.deleted_at is not None:
            raise JobFailure("policy_missing", "This claim's policy document is no longer available.", retryable=False)
        # Copied out now: eligibility_input reloads this policy row with other options, which drops `insurer`.
        # The linked reference insurer if there is one, else the name the user entered (D-46).
        insurer_name = policy.insurer.name if policy.insurer else policy.insurer_name
        policy_number, product_name = policy.policy_number, policy.product_name
        member = await session.get(Member, claim.member_id)
        events = list(await session.scalars(select(ClaimEvent).where(ClaimEvent.claim_id == claim.id).order_by(ClaimEvent.seq)))
        attached = await load_attached_documents(session, household_id, claim.id)
        assessment = assess_eligibility(await eligibility_input(session, claim), today)

    denied = [e for e in events if e.to_state == "denied"]
    last_denied = denied[-1] if denied else None
    report = compute_completeness(claim.id, claim.claim_type, claim.admission_type, attached, load_required_documents())
    letter = LetterFacts(
        rung=rung,
        addressee_template=load_grievance_rungs().rungs[rung].addressee,
        insurer_name=insurer_name,
        policy_number=policy_number,
        product_name=product_name,
        patient_name=member.full_name if member else None,
        hospital_name=claim.hospital_name,
        admitted_on=claim.admitted_on,
        discharged_on=claim.discharged_on,
        claimed_amount=claim.claimed_amount,
        denied_on=india_date(last_denied.occurred_at) if last_denied else None,
        denial_reason=last_denied.note if last_denied else None,
    )
    return DraftContext(
        household_id=household_id,
        claim_id=claim.id,
        rung=rung,
        document_id=document.id,
        letter=letter,
        checks=assessment.checks,
        band=assessment.band,
        denial_ground=claim.denial_ground,
        diagnosis=claim.diagnosis,
        current_state=events[-1].to_state if events else "unknown",
        # The policy document was checked above: it exists and is not deleted.
        evidence=evidence_checklist(report, last_denied is not None, assessment.checks, policy_document_uploaded=True),
    )


def assemble_draft(
    context: DraftContext,
    written: list[DraftParagraph],
    citations: list[Citation],
    missing_context: str | None,
    now: datetime,
    *,
    opening: RulesText | None = None,
    conditions: list[BeforeYouSendNote] | None = None,
) -> GrievanceDraft:
    """The whole draft. Only `written[].text` and the model's conditions came from the model; everything else is built here.

    Order of paragraphs: the rules' opening (D-48), the model's, then the fixed
    procedural requests (D-47) when nothing argued survived or our rules agree with the denial.
    """
    agrees = assessment_agrees(ground_check(context.checks, context.denial_ground), context.band)
    if opening is not None:
        # The letter does argue (from the rules), so "no argument paragraphs" would be untrue.
        missing_context = None
    survived = opening is not None or any(p.verified for p in written)
    paragraphs = ([opening.paragraph] if opening else []) + written
    if agrees or not survived:
        paragraphs += template_paragraphs()
    if opening is not None and opening.citation is not None:
        citations = [opening.citation, *citations]
    closing_text = closing(context.rung, enclosures(context.evidence), asks_for_explanation=agrees)
    return GrievanceDraft(
        id=new_id(),
        claim_id=context.claim_id,
        rung=context.rung,
        subject=subject(context.letter, asks_for_explanation=agrees),
        addressee=addressee(context.letter),
        header_lines=header_lines(context.letter),
        paragraphs=paragraphs,
        citations=citations,
        evidence_checklist=context.evidence,
        citation_precision=citation_precision(paragraphs),
        closing=closing_text,
        disclaimer=DISCLAIMER,
        letter_text=render_letter_text(context.letter, paragraphs, citations, closing_text, asks_for_explanation=agrees),
        missing_context=missing_context,
        assessment_note=ASSESSMENT_AGREES if agrees else None,
        # Deterministic notes first, then the model's conditions. Never in letter_text.
        before_you_send=(opening.notes if opening else []) + (conditions or []),
        generated_at=now,
    )


async def draft_letter(
    *,
    session_factory: SessionFactory,
    models: Models,
    llm: GrievanceLlm,
    context: DraftContext,
    now: datetime,
    progress: Progress = no_progress,
) -> DraftOutcome:
    """The pipeline for one letter, with no job attached. Raises ModelServerError or LlmError when a model can't answer."""
    timings: dict[str, float] = {}
    record: dict[str, Any] = {"retrieved": None, "generated": None, "verification": None, "models": {}}

    # --- retrieving ---
    await progress(RETRIEVING)
    t = time.perf_counter()
    queries = search_queries(context.letter.denial_reason, context.checks, context.denial_ground)
    per_query: list[list[Clause]] = []
    record["retrieved"] = []
    async with session_factory() as session:
        for query in queries:
            found = await retrieve(session, models, household_id=context.household_id, document_id=context.document_id, query=query)
            per_query.append(found.clauses)
            record["retrieved"].append({"query": query, "trace": found.trace})
    clauses = merge_clauses(per_query)
    timings["retrieve"] = round(time.perf_counter() - t, 3)
    # The rules' own opening paragraph (D-48), when the chosen ground's check supports the policyholder.
    opening = rules_opening(ground_check(context.checks, context.denial_ground))
    if not clauses:
        return DraftOutcome(assemble_draft(context, [], [], NO_CLAUSES, now, opening=opening), record, timings)

    # Short ids for the model; it never sees (or can invent) a database id.
    by_short_id = {f"c{i}": clause for i, clause in enumerate(clauses, start=1)}
    prompts = [ClausePrompt(id=short, page=c.page, text=c.text) for short, c in by_short_id.items()]
    facts = facts_block(context, opening)

    # --- drafting ---
    await progress(DRAFTING)
    t = time.perf_counter()
    drafted = await llm.draft(RUNG_DESCRIPTIONS[context.rung], facts, prompts)
    record["models"]["draft"] = drafted.model
    record["generated"] = drafted.value.model_dump()
    timings["draft"] = round(time.perf_counter() - t, 3)
    problem = generated_draft_problems(drafted.value, set(by_short_id))
    if problem:
        raise LlmError(f"unusable draft: {problem}", code="bad_answer", retryable=True)
    if drafted.value.abstain and not drafted.value.conditions:
        return DraftOutcome(assemble_draft(context, [], [], NOT_DRAFTED, now, opening=opening), record, timings)

    # --- verifying ---
    # Paragraphs and the model's conditions get the same two checks (D-48), in one judge call.
    await progress(VERIFYING)
    t = time.perf_counter()
    chunk_text = {short: c.text for short, c in by_short_id.items()}
    written = [Sentence(p.text, tuple(dict.fromkeys(p.chunk_ids))) for p in drafted.value.paragraphs]
    open_conditions, settled = drop_settled_conditions(drafted.value.conditions, context.checks)
    found_conditions = [Sentence(c.text, tuple(dict.fromkeys(c.chunk_ids))) for c in open_conditions]
    candidates = written + found_conditions
    # Only text that passes the number check is worth a judge's verdict.
    worth_judging = [i for i, s in enumerate(candidates) if not precheck([s], chunk_text, facts)[1]]
    pairs = [(i, chunk_id) for i in worth_judging for chunk_id in candidates[i].chunk_ids]
    prompt_by_id = {p.id: p for p in prompts}
    judged = await llm.judge_paragraphs(facts, [(candidates[i].text, prompt_by_id[chunk_id]) for i, chunk_id in pairs])
    if pairs:
        record["models"]["judge"] = judged.model
    verdicts = dict(zip(pairs, judged.value, strict=True))
    results = verify_in_order(candidates, verdicts, chunk_text, facts)
    timings["verify"] = round(time.perf_counter() - t, 3)

    def kept_ids(sentence: Sentence, outcome: Sentence | Removed) -> tuple[str, ...]:
        # Verified text keeps only the clauses judged to support it; unverified text keeps all it cited, so the user can check them.
        return outcome.chunk_ids if isinstance(outcome, Sentence) else sentence.chunk_ids

    paragraphs: list[DraftParagraph] = []
    conditions: list[BeforeYouSendNote] = []
    cited_order: list[str] = []
    for index, (sentence, outcome) in enumerate(zip(candidates, results, strict=True)):
        shorts = kept_ids(sentence, outcome)
        cited_order += [s for s in shorts if s not in cited_order]
        ids = [str(by_short_id[s].id) for s in shorts]
        verified = not isinstance(outcome, Removed)
        if index < len(written):
            paragraphs.append(DraftParagraph(text=sentence.text, citation_ids=ids, verified=verified, source="model"))
        else:
            conditions.append(BeforeYouSendNote(text=sentence.text, citation_ids=ids, source="model", verified=verified))
    record["verification"] = {
        "paragraphs": [
            {"kind": "paragraph" if i < len(written) else "condition", "verified": not isinstance(o, Removed),
             "reason": o.reason if isinstance(o, Removed) else None, "detail": o.detail if isinstance(o, Removed) else None,
             "chunk_ids": list(s.chunk_ids)}
            for i, (s, o) in enumerate(zip(candidates, results, strict=True))
        ],
        "judgements": [{"paragraph": i, "chunk_id": chunk_id, "supported": ok} for (i, chunk_id), ok in verdicts.items()],
        "conditions_dropped": settled,
    }
    citations = [Citation.model_validate(clause_citation(by_short_id[s], context.document_id)) for s in cited_order]
    missing = NOT_DRAFTED if drafted.value.abstain else None
    return DraftOutcome(
        assemble_draft(context, paragraphs, citations, missing, now, opening=opening, conditions=conditions), record, timings
    )


async def run_generate_grievance_draft(job: ClaimedJob, *, session_factory: SessionFactory, models: Models, llm: GrievanceLlm) -> None:
    started = time.perf_counter()
    # The clock is read here, at the job's edge, and passed inwards.
    now = datetime.now(timezone.utc)
    context = await load_context(session_factory, job.household_id, UUID(job.payload["claim_id"]), job.payload["rung"], india_date(now))

    async def progress(step: tuple[str, int]) -> None:
        await set_progress(session_factory, job.id, *step)

    try:
        outcome = await draft_letter(session_factory=session_factory, models=models, llm=llm, context=context, now=now, progress=progress)
    except ModelServerError as exc:
        raise JobFailure("models_unavailable", MODELS_UNAVAILABLE, retryable=True, detail=str(exc)) from exc
    except LlmError as exc:
        message = LLM_BUSY if exc.code in ("overloaded", "rate_limited", "timeout") else LLM_UNAVAILABLE
        raise JobFailure(f"llm_{exc.code}", message, retryable=exc.retryable, detail=str(exc)) from exc
    outcome.timings["total"] = round(time.perf_counter() - started, 3)
    await _finish(session_factory, job, context, outcome)


async def _finish(session_factory: SessionFactory, job: ClaimedJob, context: DraftContext, outcome: DraftOutcome) -> None:
    """The draft's record and the job's success, in one transaction."""
    result = outcome.result.model_dump(mode="json")
    async with session_factory() as session, session.begin():
        job_row = await session.get(Job, job.id, with_for_update=True)
        if job_row is None:
            raise JobFailure("job_missing", "This draft is no longer available.", retryable=False)
        session.add(
            GrievanceDraftRow(
                id=outcome.result.id,
                household_id=context.household_id,
                claim_id=context.claim_id,
                job_id=job.id,
                rung=context.rung,
                result=result,
                timings=outcome.timings,
                prompt_version=GRIEVANCE_PROMPT_VERSION,
                **outcome.record,
            )
        )
        job_row.status = "succeeded"
        job_row.progress = {"step": "done", "percent": 100}
        job_row.result = result
        job_row.finished_at = func.now()
    logger.info(
        "Drafted grievance. job_id=%s rung=%s paragraphs=%s verified=%s timings=%s",
        job.id, context.rung, len(outcome.result.paragraphs), sum(p.verified for p in outcome.result.paragraphs), outcome.timings,
    )
