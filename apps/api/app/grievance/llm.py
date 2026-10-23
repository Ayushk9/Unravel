"""The two Gemini calls of a grievance draft, each under a strict JSON schema.

    draft    claim facts + up to 6 policy clauses -> argument paragraphs, each citing clause ids, or an abstention
    judge    (paragraph, clause) pairs             -> supported / unsupported, one verdict per pair

The model writes argument paragraphs only. It is told not to restate names,
amounts or dates (the letter's header carries those, filled by code) and it
is never asked for, or allowed to cite, a regulation, a deadline or a figure
that is not in a clause. Every paragraph is then number-checked and judged
(engines/retrieval/verify.verify_in_order); one that fails is kept and
flagged, never silently passed.

GeminiGrievanceLlm reuses GeminiQaLlm's call loop (_generate): the same
retries with backoff, the same fallback model, the same LlmError codes.
Drafts are never cached (D-42).
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field

from app.qa.llm import Answered, CallOptions, ClausePrompt, GeminiQaLlm, Verdicts

# Bump when a prompt, schema or call option below changes. Stored with every draft.
GRIEVANCE_PROMPT_VERSION = "grievance-v5"

# Why these limits (diagnosed 2026-10-20; DECISIONS.md, Phase 7 Stage B):
# - The draft is composition from at most 6 given clauses under strict citation
#   rules. Some reasoning helps it choose honest grounds and keep to the rules,
#   so LOW, not MINIMAL; unbounded thinking is what made the call run past its timeout.
# - The judge gives one supported/unsupported verdict per pair: entailment
#   against a single clause, which needs little deliberation. LOW, the lowest
#   level gemini-3.8-flash accepts: it rejects MINIMAL with a 400 (found live,
#   2026-10-22; DECISIONS.md).
# - Output caps: 5 paragraphs of at most 1,200 characters is about 1,500
#   tokens of JSON, so 2,048; a list of verdicts fits well inside 1,024.
DRAFT_OPTIONS = CallOptions(thinking_level="LOW", max_output_tokens=2048)
JUDGE_OPTIONS = CallOptions(thinking_level="LOW", max_output_tokens=1024)

MAX_PARAGRAPHS = 5
MAX_CONDITIONS = 4


class GeneratedParagraph(BaseModel):
    text: str = Field(min_length=1, max_length=1200)
    chunk_ids: list[str] = Field(min_length=1, max_length=4)


# The eligibility checks a condition can restate, or "none" (a requirement the rules do not check).
RestatedCheck = Literal[
    "none", "initial_waiting_period", "ped_waiting_period", "disease_specific_waiting_period",
    "permanent_exclusions", "room_rent_sub_limit", "claim_intimation", "sum_insured_adequacy",
]


class GeneratedCondition(BaseModel):
    """A condition written in a cited clause that the insurer could rely on. Shown before sending, never in the letter (D-48)."""

    text: str = Field(min_length=1, max_length=400)
    chunk_ids: list[str] = Field(min_length=1, max_length=2)
    # Which eligibility check's own requirement this condition restates, if any. A condition restating
    # a check the rules already found SATISFIED is dropped by code (run_draft.drop_settled_conditions).
    restates_check: RestatedCheck = "none"


class GeneratedDraft(BaseModel):
    # One object with an `abstain` flag, as for Q&A answers (app/qa/llm.py explains why).
    abstain: bool
    reason: str | None = None
    paragraphs: list[GeneratedParagraph] = Field(default_factory=list, max_length=MAX_PARAGRAPHS)
    conditions: list[GeneratedCondition] = Field(default_factory=list, max_length=MAX_CONDITIONS)


class GrievanceLlm(Protocol):
    async def draft(self, rung_description: str, facts: str, clauses: list[ClausePrompt]) -> Answered[GeneratedDraft]: ...

    async def judge_paragraphs(self, facts: str, pairs: list[tuple[str, ClausePrompt]]) -> Answered[list[bool]]: ...


RUNG_DESCRIPTIONS = {
    "insurer_grievance_cell": "a letter to the insurer's grievance redressal officer asking for the claim decision to be reviewed",
    "irdai_bima_bharosa": "a grievance registered with the insurance regulator (IRDAI) about the insurer's handling of the claim",
    "insurance_ombudsman": "a complaint to the Insurance Ombudsman about the insurer's decision on the claim",
}

DRAFT_PROMPT = """You help a policyholder in India write the argument paragraphs of {rung_description}.
The letter's header, greeting, closing and signature are written separately. Write ONLY the argument paragraphs.

Use ONLY the CLAIM FACTS and the POLICY CLAUSES given below.

What you may argue from:
- ONLY the claim's facts and the CHECKS THAT SUPPORT THE POLICYHOLDER listed in the CLAIM FACTS.
- Every paragraph must cite, by id (c1, c2, ...), the clause or clauses that support each thing it says about the policy.

What you must not do:
- Do not introduce optional covers, add-ons, portability, migration, buy-back or any other benefit that the CLAIM FACTS do not mention.
- Do not raise, quote or hint at any condition, exclusion or requirement that could count against the policyholder. Put such
  conditions in "conditions" instead (see below), never in a paragraph.
- Do not repeat the opening paragraph given in the CLAIM FACTS, if there is one.
- State nothing about the policy that is not written in the clauses you cite. Do not use general knowledge about insurance.
- Do not mention any law, regulation, circular, regulator rule, deadline, time limit or award limit.
- Do not write names, policy numbers, amounts or dates. The letter states them elsewhere.
- Do not do arithmetic. Do not contradict the CLAIM FACTS.
- Do not promise or predict an outcome. Do not threaten. Do not give legal advice.

Style: first person, polite, plain English. 2 to 4 sentences per paragraph. At most {max_paragraphs} paragraphs.
If the supporting checks and clauses give no honest ground for the letter, set "abstain" to true, give a short reason, and return no paragraphs.

"conditions": list (at most {max_conditions}) conditions written in the clauses you were given that the insurer could rely on
against this claim, each in one plain sentence that says only what the clause says, citing its clause id. These are shown
to the policyholder privately before sending, never put in the letter. Return an empty list if there are none.
For each condition set "restates_check" to the id of the check whose OWN requirement it restates, if it is exactly that
requirement (for example the length of the initial waiting period -> "initial_waiting_period"); otherwise "none".
A further requirement that no check evaluates (for example that a disease had to be declared at application) is "none".
Check ids: initial_waiting_period, ped_waiting_period, disease_specific_waiting_period, permanent_exclusions,
room_rent_sub_limit, claim_intimation, sum_insured_adequacy.
"""

JUDGE_PROMPT = """You check paragraphs of a policyholder's grievance letter against the policy's own text.
For each numbered pair, decide whether the paragraph is supported.
"supported" means: everything the PARAGRAPH states about what the policy says is stated in the CLAUSE, including every number,
and everything it states about the claim agrees with the CLAIM FACTS.
Requests, questions and polite phrases ("I request you to review...") need no support.
"unsupported" means the clause does not say it, says something different, or only partly supports it.
Judge each pair independently. Do not use outside knowledge.
"""


def generated_draft_problems(draft: GeneratedDraft, clause_ids: set[str]) -> str | None:
    """Why a parsed draft can't be used, or None if it is well formed."""
    if draft.abstain and draft.paragraphs:
        return "abstained but also gave paragraphs"
    if not draft.abstain and not draft.paragraphs:
        return "did not abstain but gave no paragraphs"
    unknown = {cid for p in [*draft.paragraphs, *draft.conditions] for cid in p.chunk_ids} - clause_ids
    if unknown:
        return f"cited clause ids it was not given: {sorted(unknown)}"
    return None


def _clause_listing(clauses: list[ClausePrompt]) -> str:
    return "\n\n".join(f"[{c.id}] (page {c.page})\n{c.text}" for c in clauses)


def draft_contents(rung_description: str, facts: str, clauses: list[ClausePrompt]) -> list[str]:
    """Exactly what the draft call sends. scripts/diagnose_draft_call.py sends the same."""
    prompt = DRAFT_PROMPT.format(rung_description=rung_description, max_paragraphs=MAX_PARAGRAPHS, max_conditions=MAX_CONDITIONS)
    return [prompt, f"CLAIM FACTS:\n{facts}", f"POLICY CLAUSES:\n{_clause_listing(clauses)}"]


class GeminiGrievanceLlm(GeminiQaLlm):
    async def draft(self, rung_description: str, facts: str, clauses: list[ClausePrompt]) -> Answered[GeneratedDraft]:
        result, model = await self._generate(draft_contents(rung_description, facts, clauses), GeneratedDraft, DRAFT_OPTIONS)
        assert isinstance(result, GeneratedDraft)
        return Answered(result, model)

    async def judge_paragraphs(self, facts: str, pairs: list[tuple[str, ClausePrompt]]) -> Answered[list[bool]]:
        """One call for all pairs. A pair the model leaves out counts as unsupported."""
        if not pairs:
            return Answered([], self._model)
        listing = "\n\n".join(
            f"PAIR {i}\nPARAGRAPH: {paragraph}\nCLAUSE (page {clause.page}): {clause.text}" for i, (paragraph, clause) in enumerate(pairs)
        )
        result, model = await self._generate([JUDGE_PROMPT, f"CLAIM FACTS:\n{facts}", listing], Verdicts, JUDGE_OPTIONS)
        assert isinstance(result, Verdicts)
        supported = {v.pair for v in result.verdicts if v.verdict == "supported"}
        return Answered([i in supported for i in range(len(pairs))], model)
