"""Which answer sentences reach the user, and the answer text built from them.

The pipeline (apps/api/app/qa/run_question.py) calls these in order:

  1. precheck(): the number check against everything a sentence cites (plus
     the question). A sentence that fails is removed now and never judged,
     which saves a model call.
  2. The API asks the support judge about every remaining (sentence, clause)
     pair.
  3. decide(): a citation the judge rejected is dropped. A sentence survives
     only if it still has at least one citation AND the number check still
     passes against the clauses that remain. Checking numbers again matters:
     a sentence citing clauses A and B could take its number from B while
     only A is judged to support it.
  4. assemble(): the surviving sentences, each followed by its [[n]] markers,
     and the ordered list of clauses they cite (D-42).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engines.retrieval.quantities import missing_numbers

NUMBER_REASON = "A number in this sentence is not in the clause it cites."
SUPPORT_REASON = "None of the clauses it cites supports it."


@dataclass(frozen=True)
class Sentence:
    text: str
    chunk_ids: tuple[str, ...]


@dataclass(frozen=True)
class Removed:
    sentence: Sentence
    reason: str
    detail: str = ""


@dataclass
class Outcome:
    kept: list[Sentence] = field(default_factory=list)
    removed: list[Removed] = field(default_factory=list)

    @property
    def checked(self) -> int:
        return len(self.kept) + len(self.removed)


def _sources(chunk_ids: tuple[str, ...], chunk_text: dict[str, str], question: str) -> list[str]:
    # The user's own question counts as a source of numbers: it is their premise, not a claim about the policy.
    return [chunk_text[chunk_id] for chunk_id in chunk_ids] + [question]


def precheck(sentences: list[Sentence], chunk_text: dict[str, str], question: str) -> tuple[list[Sentence], list[Removed]]:
    """Split sentences into those worth judging and those already failed by the number check."""
    passed, removed = [], []
    for sentence in sentences:
        missing = missing_numbers(sentence.text, _sources(sentence.chunk_ids, chunk_text, question))
        if missing:
            removed.append(Removed(sentence, NUMBER_REASON, ", ".join(map(str, missing))))
        else:
            passed.append(sentence)
    return passed, removed


def decide(
    candidates: list[Sentence],
    verdicts: dict[tuple[int, str], bool],
    chunk_text: dict[str, str],
    question: str,
    already_removed: list[Removed],
) -> Outcome:
    """Apply the judge's verdicts. `verdicts[(i, chunk_id)]` is True when clause chunk_id supports candidates[i].

    A missing verdict counts as unsupported: nothing is assumed in the answer's favour.
    """
    outcome = Outcome(removed=list(already_removed))
    for index, sentence in enumerate(candidates):
        supported = tuple(chunk_id for chunk_id in sentence.chunk_ids if verdicts.get((index, chunk_id), False))
        if not supported:
            outcome.removed.append(Removed(sentence, SUPPORT_REASON))
            continue
        missing = missing_numbers(sentence.text, _sources(supported, chunk_text, question))
        if missing:
            outcome.removed.append(Removed(sentence, NUMBER_REASON, ", ".join(map(str, missing))))
            continue
        outcome.kept.append(Sentence(sentence.text, supported))
    return outcome


def assemble(kept: list[Sentence]) -> tuple[str, list[str]]:
    """The answer text with [[n]] markers, and the cited chunk ids in marker order.

    n is the 1-indexed position in the returned list. A clause cited by two
    sentences appears once and gets the same n both times.
    """
    order: list[str] = []
    parts = []
    for sentence in kept:
        markers = []
        for chunk_id in sentence.chunk_ids:
            if chunk_id not in order:
                order.append(chunk_id)
            markers.append(f"[[{order.index(chunk_id) + 1}]]")
        parts.append(f"{sentence.text.strip()} {''.join(markers)}")
    return " ".join(parts), order
