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

from typing import Protocol

from pydantic import BaseModel, Field

from app.qa.llm import Answered, ClausePrompt, GeminiQaLlm, Verdicts

# Bump when a prompt or schema below changes. Stored with every draft.
GRIEVANCE_PROMPT_VERSION = "grievance-v1"

MAX_PARAGRAPHS = 5


class GeneratedParagraph(BaseModel):
    text: str = Field(min_length=1, max_length=1200)
    chunk_ids: list[str] = Field(min_length=1, max_length=4)


class GeneratedDraft(BaseModel):
    # One object with an `abstain` flag, as for Q&A answers (app/qa/llm.py explains why).
    abstain: bool
    reason: str | None = None
    paragraphs: list[GeneratedParagraph] = Field(default_factory=list, max_length=MAX_PARAGRAPHS)


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

Rules:
- Every paragraph must cite, by id (c1, c2, ...), the clause or clauses that support each thing it says about the policy.
- State nothing about the policy that is not written in the clauses you cite. Do not use general knowledge about insurance.
- Do not mention any law, regulation, circular, regulator rule, deadline, time limit or award limit.
- Do not write names, policy numbers, amounts or dates. The header already states them.
- Do not do arithmetic. Do not contradict the CLAIM FACTS.
- Be honest: if a clause supports the insurer's decision, do not pretend otherwise. You may ask the insurer to point to the exact clause it relied on, or point out a clause that supports cover.
- Do not promise or predict an outcome. Do not threaten. Do not give legal advice.
- First person, polite, plain English. 2 to 4 sentences per paragraph. At most {max_paragraphs} paragraphs.
- If the clauses give no honest ground for the letter, set "abstain" to true, give a short reason, and return no paragraphs.
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
    if draft.abstain:
        return "abstained but also gave paragraphs" if draft.paragraphs else None
    if not draft.paragraphs:
        return "did not abstain but gave no paragraphs"
    unknown = {cid for p in draft.paragraphs for cid in p.chunk_ids} - clause_ids
    if unknown:
        return f"cited clause ids it was not given: {sorted(unknown)}"
    return None


def _clause_listing(clauses: list[ClausePrompt]) -> str:
    return "\n\n".join(f"[{c.id}] (page {c.page})\n{c.text}" for c in clauses)


class GeminiGrievanceLlm(GeminiQaLlm):
    async def draft(self, rung_description: str, facts: str, clauses: list[ClausePrompt]) -> Answered[GeneratedDraft]:
        prompt = DRAFT_PROMPT.format(rung_description=rung_description, max_paragraphs=MAX_PARAGRAPHS)
        result, model = await self._generate([prompt, f"CLAIM FACTS:\n{facts}", f"POLICY CLAUSES:\n{_clause_listing(clauses)}"], GeneratedDraft)
        assert isinstance(result, GeneratedDraft)
        return Answered(result, model)

    async def judge_paragraphs(self, facts: str, pairs: list[tuple[str, ClausePrompt]]) -> Answered[list[bool]]:
        """One call for all pairs. A pair the model leaves out counts as unsupported."""
        if not pairs:
            return Answered([], self._model)
        listing = "\n\n".join(
            f"PAIR {i}\nPARAGRAPH: {paragraph}\nCLAUSE (page {clause.page}): {clause.text}" for i, (paragraph, clause) in enumerate(pairs)
        )
        result, model = await self._generate([JUDGE_PROMPT, f"CLAIM FACTS:\n{facts}", listing], Verdicts)
        assert isinstance(result, Verdicts)
        supported = {v.pair for v in result.verdicts if v.verdict == "supported"}
        return Answered([i in supported for i in range(len(pairs))], model)
