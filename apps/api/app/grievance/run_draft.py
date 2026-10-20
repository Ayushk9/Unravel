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
from app.grievance.letter import DISCLAIMER, LetterFacts, addressee, closing, header_lines, render_letter_text, subject
from app.grievance.llm import GRIEVANCE_PROMPT_VERSION, RUNG_DESCRIPTIONS, GrievanceLlm, generated_draft_problems
from app.jobs.parse_document import JobFailure
from app.jobs.queue import ClaimedJob, SessionFactory, set_progress
from app.models_server.client import Models, ModelServerError
from app.qa.llm import ClausePrompt, LlmError
from app.qa.retrieval import Clause, retrieve
from app.qa.run_question import Progress, clause_citation, no_progress
from app.rules.loader import load_grievance_rungs, load_required_documents
from app.rules_bridge import eligibility_input
from app.schemas.grievances import DraftParagraph, EvidenceItem, GrievanceDraft
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
    diagnosis: str | None
    current_state: str
    evidence: list[EvidenceItem]


@dataclass
class DraftOutcome:
    result: GrievanceDraft
    record: dict[str, Any]
    timings: dict[str, float]


def citation_precision(paragraphs: list[DraftParagraph]) -> float:
    """Verified paragraphs / all paragraphs. 0 when there are none (the draft then says why in missing_context)."""
    if not paragraphs:
        return 0.0
    return sum(1 for p in paragraphs if p.verified) / len(paragraphs)


def search_queries(denial_reason: str | None, checks: tuple[CheckResult, ...]) -> list[str]:
    """What to search the policy for: the recorded denial reason, then each failed or at-risk check."""
    queries = [denial_reason.strip()] if denial_reason and denial_reason.strip() else []
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


def facts_block(context: DraftContext) -> str:
    """The claim facts the model may argue from, and the judge checks claim statements against. All from the database."""
    lines = [f"Claim status: {context.current_state.replace('_', ' ')}"]
    if context.letter.denial_reason:
        lines.append(f"Reason for denial, as recorded by the policyholder: “{context.letter.denial_reason}”")
    if context.diagnosis:
        lines.append(f"Diagnosis, as entered by the policyholder: {context.diagnosis}")
    flagged = [c for c in context.checks if c.status in ("failed", "at_risk", "unknown")]
    if flagged:
        lines.append("Checks of the claim against the policy, made by rules on the policyholder's documents:")
        lines += [f"- {c.title}: {c.status.replace('_', ' ')}. {c.explanation}" for c in flagged]
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
        diagnosis=claim.diagnosis,
        current_state=events[-1].to_state if events else "unknown",
        evidence=evidence_checklist(report, last_denied is not None, assessment.checks),
    )


def assemble_draft(
    context: DraftContext, paragraphs: list[DraftParagraph], citations: list[Citation], missing_context: str | None, now: datetime
) -> GrievanceDraft:
    """The whole draft. Only `paragraphs[].text` came from the model; every other field is built here."""
    closing_text = closing(context.rung, enclosures(context.evidence))
    return GrievanceDraft(
        id=new_id(),
        claim_id=context.claim_id,
        rung=context.rung,
        subject=subject(context.letter),
        addressee=addressee(context.letter),
        header_lines=header_lines(context.letter),
        paragraphs=paragraphs,
        citations=citations,
        evidence_checklist=context.evidence,
        citation_precision=citation_precision(paragraphs),
        closing=closing_text,
        disclaimer=DISCLAIMER,
        letter_text=render_letter_text(context.letter, paragraphs, citations, closing_text),
        missing_context=missing_context,
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
    queries = search_queries(context.letter.denial_reason, context.checks)
    per_query: list[list[Clause]] = []
    record["retrieved"] = []
    async with session_factory() as session:
        for query in queries:
            found = await retrieve(session, models, household_id=context.household_id, document_id=context.document_id, query=query)
            per_query.append(found.clauses)
            record["retrieved"].append({"query": query, "trace": found.trace})
    clauses = merge_clauses(per_query)
    timings["retrieve"] = round(time.perf_counter() - t, 3)
    if not clauses:
        return DraftOutcome(assemble_draft(context, [], [], NO_CLAUSES, now), record, timings)

    # Short ids for the model; it never sees (or can invent) a database id.
    by_short_id = {f"c{i}": clause for i, clause in enumerate(clauses, start=1)}
    prompts = [ClausePrompt(id=short, page=c.page, text=c.text) for short, c in by_short_id.items()]
    facts = facts_block(context)

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
    if drafted.value.abstain:
        return DraftOutcome(assemble_draft(context, [], [], NOT_DRAFTED, now), record, timings)

    # --- verifying ---
    await progress(VERIFYING)
    t = time.perf_counter()
    chunk_text = {short: c.text for short, c in by_short_id.items()}
    written = [Sentence(p.text, tuple(dict.fromkeys(p.chunk_ids))) for p in drafted.value.paragraphs]
    # Only paragraphs that pass the number check are worth a judge's verdict.
    worth_judging = [i for i, s in enumerate(written) if not precheck([s], chunk_text, facts)[1]]
    pairs = [(i, chunk_id) for i in worth_judging for chunk_id in written[i].chunk_ids]
    prompt_by_id = {p.id: p for p in prompts}
    judged = await llm.judge_paragraphs(facts, [(written[i].text, prompt_by_id[chunk_id]) for i, chunk_id in pairs])
    if pairs:
        record["models"]["judge"] = judged.model
    verdicts = dict(zip(pairs, judged.value, strict=True))
    results = verify_in_order(written, verdicts, chunk_text, facts)
    timings["verify"] = round(time.perf_counter() - t, 3)

    paragraphs: list[DraftParagraph] = []
    cited_order: list[str] = []
    for sentence, outcome in zip(written, results, strict=True):
        verified = not isinstance(outcome, Removed)
        # A verified paragraph keeps only the clauses judged to support it; an
        # unverified one keeps all it cited, so the user can check them.
        shorts = outcome.chunk_ids if isinstance(outcome, Sentence) else sentence.chunk_ids
        cited_order += [s for s in shorts if s not in cited_order]
        paragraphs.append(DraftParagraph(text=sentence.text, citation_ids=[str(by_short_id[s].id) for s in shorts], verified=verified))
    record["verification"] = {
        "paragraphs": [
            {"verified": not isinstance(o, Removed), "reason": o.reason if isinstance(o, Removed) else None,
             "detail": o.detail if isinstance(o, Removed) else None, "chunk_ids": list(s.chunk_ids)}
            for s, o in zip(written, results, strict=True)
        ],
        "judgements": [{"paragraph": i, "chunk_id": chunk_id, "supported": ok} for (i, chunk_id), ok in verdicts.items()],
    }
    citations = [Citation.model_validate(clause_citation(by_short_id[s], context.document_id)) for s in cited_order]
    return DraftOutcome(assemble_draft(context, paragraphs, citations, None, now), record, timings)


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
