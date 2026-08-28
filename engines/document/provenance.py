"""Recover a document location for an LLM-extracted value, and compute how
much to trust it.

Two responsibilities live here on purpose, not split across files:
matching `source_text` back into the parsed document (section 4 of the task
brief) and turning the quality of that match into a confidence tier
(section 5). Confidence is entirely a function of *how the match went* —
computing it anywhere except right next to the matcher would mean
duplicating the match-quality signals (which table vs text item, how
strong the score was) into a second place that could drift out of sync
with this one.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from rapidfuzz import fuzz

import _bootstrap  # noqa: F401 — puts the repo root on sys.path for `contracts`
from contracts.models import Provenance
from docling_core.types.doc.base import BoundingBox
from docling_wrapper import PageInfo, ParsedDocument, TableCellRecord, TableRecord
from geometry import normalise_bbox

# Fuzzy matching is required, not optional, because exact string equality
# fails often and for boring reasons: whitespace differences from markdown
# reflow, ligatures, and the "/-" rupee suffix the model may or may not
# have copied. STRONG_MATCH_THRESHOLD is informational only now (surfaced
# in Match.is_strong for scripts/verify_extraction.py to display) — it no
# longer gates confidence; see compute_confidence's docstring for why the
# validity gate below made that unnecessary.
STRONG_MATCH_THRESHOLD = 95.0
WEAK_MATCH_THRESHOLD = 85.0

# --- Validity gate (Fix 1) --------------------------------------------------
#
# Incident: co_pay_percent, a sub-limit, and an exclusion all resolved to a
# single-character cell ("1"), three different waiting periods all resolved
# to one cell ("All"), and a Rs.2,50,000 sub-limit resolved to a cell reading
# "5,00,000/-" — all scored "high". The cause was never the similarity
# threshold: partial_ratio on a 1-character candidate against almost any
# longer target trivially scores near 100 (the "best window" is just that
# one character), and a fuzzy score alone can't tell "wrong number of
# similar shape" from "right number, formatting noise". Raising
# WEAK_MATCH_THRESHOLD doesn't fix either failure mode — a length/geometry
# gate and a value-containment check are checking different, necessary
# things, so a candidate must clear ALL of them before its score is even
# considered. A wrong highlight is worse than no highlight (it launders a
# bad extraction as verified) — so the gate is deliberately allowed to
# reject genuine matches too, in exchange for never accepting a bad one.
MIN_MATCH_LENGTH = 12  # normalised chars, required on BOTH source_text and candidate
MIN_BBOX_WIDTH_POINTS = 8.0  # the "1" cell above was 4pt wide; a real short cell ("5,00,000/-") is ~50pt
MIN_BBOX_HEIGHT_POINTS = 3.0  # catches a degenerate/malformed bbox, not real single-line rows
MIN_SHARED_CONTENT_TOKENS = 2  # capped at however many content tokens the target actually has

_STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "at", "for", "is", "are",
    "was", "were", "be", "as", "by", "with", "from", "that", "this", "all", "any",
    "per", "not", "no", "if", "it", "its", "may", "shall", "will", "such", "up",
}

_PUNCTUATION_PATTERN = re.compile(r"[₹$,/\-–—]")
_WHITESPACE_PATTERN = re.compile(r"\s+")
_NON_DIGIT_PATTERN = re.compile(r"\D")

# A normalised string counts as a "numeric token" (a money amount, a month
# count, an hour count) once at least this fraction of its non-space
# characters are digits, with a floor on digit count so a single stray
# digit in a sentence doesn't trip it.
_NUMERIC_DIGIT_RATIO_THRESHOLD = 0.6
_NUMERIC_MIN_DIGITS = 2


def _normalise_for_match(text: str) -> str:
    """Collapse whitespace and strip currency punctuation before comparing.

    Both sides of every comparison go through this, so stripping "-"
    unconditionally (even from e.g. "pre-existing") is safe — it never
    changes which side wins a comparison, only makes exact matches survive
    formatting noise like "5,00,000/-" vs "500000".
    """
    text = _PUNCTUATION_PATTERN.sub("", text)
    text = _WHITESPACE_PATTERN.sub(" ", text)
    return text.strip().lower()


def _digits_only(text: str) -> str:
    return _NON_DIGIT_PATTERN.sub("", text)


def _is_numeric_token(normalised_text: str) -> bool:
    non_space = normalised_text.replace(" ", "")
    digits = _digits_only(non_space)
    if len(digits) < _NUMERIC_MIN_DIGITS or not non_space:
        return False
    return len(digits) / len(non_space) >= _NUMERIC_DIGIT_RATIO_THRESHOLD


def _match_score(target: str, candidate: str) -> float:
    """Score two already-normalised strings — the one function in this
    module most worth reading carefully.

    Numeric content (money amounts, month counts, hour counts) is compared
    by exact digit-string equality, never by edit-distance ratio. Two
    different rupee amounts of similar length score deceptively high under
    any fuzzy metric — "5,00,000" vs "7,50,000" scores ~83-91 depending on
    the algorithm, comfortably inside what would otherwise be the "weak
    match" band, which would make the matcher confidently point a sub-limit
    at a different row's amount. There is no such thing as "the right
    number, 85% of the way" — a digit sequence either is the one that was
    extracted, or it names a different, wrong fact. When only one side is
    numeric-dominant (a bare number matched against a prose sentence that
    contains it — e.g. a waiting-period quote against the text item it came
    from), the number is searched for as a whole token (word-boundaried, so
    "36" cannot match inside "436" or "360") rather than compared digit-run
    to digit-run, since the prose side legitimately carries other digits
    around it (section numbers, dates).

    Prose content uses partial_ratio, which is substring-tolerant: the
    model's source_text quote is frequently a short, complete sentence
    embedded inside a longer Docling text item spanning a whole paragraph.
    """
    target_numeric = _is_numeric_token(target)
    candidate_numeric = _is_numeric_token(candidate)

    if target_numeric and candidate_numeric:
        return 100.0 if _digits_only(target) == _digits_only(candidate) else 0.0

    if target_numeric or candidate_numeric:
        numeric_text, prose_text = (target, candidate) if target_numeric else (candidate, target)
        digits = _digits_only(numeric_text)
        token_pattern = re.compile(rf"(?<!\d){re.escape(digits)}(?!\d)")
        return 100.0 if token_pattern.search(prose_text) else 0.0

    return fuzz.partial_ratio(target, candidate)


def _content_tokens(normalised_text: str) -> set[str]:
    """Whitespace tokens, minus stopwords and anything too short to carry
    meaning on its own. A pure number ("500000") survives this as a single
    token — see the docstring on _passes_token_overlap for why that's the
    correct behaviour, not an oversight.
    """
    return {tok for tok in normalised_text.split() if len(tok) >= 3 and tok not in _STOPWORDS}


def _passes_token_overlap(target_norm: str, candidate_norm: str) -> bool:
    """At least MIN_SHARED_CONTENT_TOKENS words in common, capped at however
    many content tokens the target actually has.

    Guards against a *longer* candidate that clears the length gate and
    still scores well on partial_ratio purely by sharing common connector
    words ("or", "and", "with") with the target, while sharing no actual
    content. A target that's itself just one number ("500000") only has one
    content token to begin with, so the cap keeps that case from being
    impossible to pass — the numeric-equality branch of _match_score is
    already the strict check for that case; this gate isn't meant to
    re-litigate it, only to catch prose collisions.
    """
    target_tokens = _content_tokens(target_norm)
    if not target_tokens:
        return True  # nothing to check token overlap against — length/bbox/containment gates still apply
    candidate_tokens = _content_tokens(candidate_norm)
    required = min(MIN_SHARED_CONTENT_TOKENS, len(target_tokens))
    return len(target_tokens & candidate_tokens) >= required


def _bbox_size_ok(bbox: BoundingBox) -> bool:
    """Reject a candidate whose bbox is physically too small to be a real,
    distinctive piece of content — the single-character "1" cell that
    started this fix was 4pt wide; a genuine short numeric cell
    ("5,00,000/-") is ~50pt wide. Width/height here are origin-independent
    (|r-l|, |t-b|), so this needs no coord_origin awareness."""
    width = abs(bbox.r - bbox.l)
    height = abs(bbox.t - bbox.b)
    return width >= MIN_BBOX_WIDTH_POINTS and height >= MIN_BBOX_HEIGHT_POINTS


def _passes_value_containment(candidate_norm: str, value_text: str | None) -> bool:
    """When the caller supplies the actual parsed value's raw text (not just
    source_text — the two can disagree when the model's quote and its own
    structured field drift apart), the candidate must contain that value's
    digits. This is what catches "Rs.2,50,000 resolved to a cell reading
    5,00,000/-": same shape, different number, source_text alone can't
    distinguish them but the value itself does.
    """
    if value_text is None:
        return True
    value_digits = _digits_only(value_text)
    if len(value_digits) < 2:
        # A single digit ("1" month of initial waiting period is a real,
        # plausible value) is too short to check by substring containment —
        # it would trivially match almost any candidate that has a "1"
        # anywhere in it (a clause number, a page reference, another
        # amount). Rely on the length/bbox/token-overlap gates instead;
        # cross-field dedup (deduplicate_by_location) is the backstop for
        # exactly this case if several such fields collide on one cell.
        return True
    return value_digits in _digits_only(candidate_norm)


def _passes_gate(
    *,
    target_norm: str,
    candidate_norm: str,
    candidate_bbox: BoundingBox,
    value_text: str | None,
) -> bool:
    """Every check a candidate must clear before its fuzzy score is even
    computed. See the module-level comment above MIN_MATCH_LENGTH for why
    this exists as a gate rather than a higher similarity threshold."""
    if len(target_norm) < MIN_MATCH_LENGTH or len(candidate_norm) < MIN_MATCH_LENGTH:
        return False
    if not _bbox_size_ok(candidate_bbox):
        return False
    if not _passes_value_containment(candidate_norm, value_text):
        return False
    if not _passes_token_overlap(target_norm, candidate_norm):
        return False
    return True


@dataclass(frozen=True)
class Match:
    """The result of matching one source_text against the parsed document.

    Carries the originating `table`/`cell` (not just its bbox) so
    domain-specific callers — e.g. sub-limit assembly, checking whether a
    cell's column header was duplicated across a merged span (SPIKE_NOTES.md
    finding 4) — can inspect the table structure without provenance.py
    needing to know anything about sub-limits.
    """

    matched_via: Literal["cell", "text_item", "none"]
    score: float
    page_no: int | None
    bbox: BoundingBox | None
    snippet: str | None
    table: TableRecord | None = None
    cell: TableCellRecord | None = None

    @property
    def is_strong(self) -> bool:
        return self.score >= STRONG_MATCH_THRESHOLD


NO_MATCH = Match(matched_via="none", score=0.0, page_no=None, bbox=None, snippet=None)


def find_best_match(
    source_text: str | None,
    parsed: ParsedDocument,
    *,
    value_text: str | None = None,
) -> Match:
    """Match source_text against table cells first, then text items.

    `value_text` is the raw text of the value actually extracted for this
    field (e.g. a sub-limit's cap_amount_raw, or str(10.0) for a co-pay
    percent) — separate from source_text, because the two can disagree.
    When supplied, every candidate must contain its digits (see
    _passes_value_containment) or it's rejected outright, regardless of how
    well source_text fuzzy-matches. Pass None for fields where containment
    isn't meaningful (exclusion prose, applies_to text).

    A single fuzzy pass (rather than a separate exact-match pass followed
    by a fuzzy one) is enough to satisfy "exact and then fuzzy": an exact
    match after normalisation scores 100, which always wins the max search
    below, so a dedicated exact pass would just be a redundant special case
    of the same comparison.

    Every candidate must clear _passes_gate before its score is even
    considered — this is Fix 1 (see the module comment above
    MIN_MATCH_LENGTH). Whichever table cell then scores highest is returned
    as soon as it clears WEAK_MATCH_THRESHOLD, even if some text item
    elsewhere would have scored higher — a cell-level bbox is a strictly
    more useful result for the UI (it can highlight one cell, not
    "somewhere in this table"), so the task brief's "best outcome" framing
    is read here as a preference for cell provenance, not just a search
    order.
    """
    if not source_text or not source_text.strip():
        return NO_MATCH

    target = _normalise_for_match(source_text)
    if not target or len(target) < MIN_MATCH_LENGTH:
        return NO_MATCH

    best_cell = NO_MATCH
    for table in parsed.tables:
        for cell in table.cells:
            candidate = _normalise_for_match(cell.text)
            if not candidate:
                continue
            if not _passes_gate(target_norm=target, candidate_norm=candidate, candidate_bbox=cell.bbox, value_text=value_text):
                continue
            score = _match_score(target, candidate)
            if score > best_cell.score:
                best_cell = Match(
                    matched_via="cell",
                    score=score,
                    page_no=table.page_no,
                    bbox=cell.bbox,
                    snippet=cell.text,
                    table=table,
                    cell=cell,
                )
    if best_cell.score >= WEAK_MATCH_THRESHOLD:
        return best_cell

    best_text_item = NO_MATCH
    for item in parsed.text_items:
        candidate = _normalise_for_match(item.text)
        if not candidate:
            continue
        if not _passes_gate(target_norm=target, candidate_norm=candidate, candidate_bbox=item.bbox, value_text=value_text):
            continue
        score = _match_score(target, candidate)
        if score > best_text_item.score:
            best_text_item = Match(
                matched_via="text_item", score=score, page_no=item.page_no, bbox=item.bbox, snippet=item.text
            )
    if best_text_item.score >= WEAK_MATCH_THRESHOLD:
        return best_text_item

    return NO_MATCH


def deduplicate_by_location(matches: dict[str, Match]) -> tuple[dict[str, Match], list[str]]:
    """Second half of Fix 1: the per-candidate gate in find_best_match can
    only see one field's match at a time, so it can't catch three different
    waiting periods all resolving to the identical (page, bbox) — each of
    those three calls looked fine in isolation. This runs once, after every
    field for a document has been matched, across the whole set: any group
    of fields sharing an exact (page, raw bbox) is collapsed to keep only
    the single highest-scoring field there, and every other field in that
    group is demoted to NO_MATCH. A shared location is prima facie evidence
    that at most one of them is really pointing at that cell.
    """
    warnings: list[str] = []
    groups: dict[tuple[int, tuple[float, float, float, float]], list[str]] = defaultdict(list)
    for name, match in matches.items():
        if match.matched_via == "none" or match.page_no is None or match.bbox is None:
            continue
        key = (match.page_no, (match.bbox.l, match.bbox.t, match.bbox.r, match.bbox.b))
        groups[key].append(name)

    result = dict(matches)
    for (page_no, bbox_key), names in groups.items():
        if len(names) <= 1:
            continue
        best_name = max(names, key=lambda n: matches[n].score)
        losers = [n for n in names if n != best_name]
        warnings.append(
            f"provenance collision at page {page_no}, bbox {bbox_key}: fields {names} all matched the same "
            f"location; kept {best_name!r} (highest score {matches[best_name].score:.1f}), "
            f"demoted {losers} to no provenance"
        )
        for name in losers:
            result[name] = NO_MATCH
    return result, warnings


def build_provenance(
    match: Match,
    document_id: UUID,
    pages: dict[int, PageInfo],
    warnings: list[str],
) -> Provenance | None:
    """Turn a Match into a contracts.Provenance, normalising its bbox.

    A page-dimension failure (e.g. the zero-size pages Docling can emit for
    a page it partially failed to parse — see docling_wrapper.py) degrades
    to page+snippet with no bbox rather than dropping provenance entirely:
    the UI still gets "which page, which quote", it just can't draw a
    highlight box. The failure is always logged to `warnings`, never
    silent.
    """
    if match.matched_via == "none" or match.page_no is None or match.bbox is None:
        return None

    page_info = pages.get(match.page_no)
    if page_info is None:
        warnings.append(
            f"matched provenance on page {match.page_no}, but that page is missing from the parsed document"
        )
        return Provenance(document_id=document_id, page=match.page_no, bbox=None, snippet=match.snippet)

    try:
        normalised = normalise_bbox(match.bbox, page_info.width, page_info.height)
    except ValueError as exc:
        warnings.append(f"could not normalise matched bbox on page {match.page_no}: {exc}")
        return Provenance(document_id=document_id, page=match.page_no, bbox=None, snippet=match.snippet)

    return Provenance(document_id=document_id, page=match.page_no, bbox=normalised, snippet=match.snippet)


def compute_confidence(
    *,
    match: Match,
    value_is_present: bool,
    value_parsed_cleanly: bool,
    basis_from_spanned_header: bool = False,
) -> Literal["high", "medium", "low"]:
    """Deterministic three-tier ladder, evaluated in this exact order.

    1. LOW — failed the gate, no match, or the value came from prose: the
       model returned no value, or nothing in the document passed
       find_best_match's validity gate (Fix 1) at all. A fact we cannot
       point at in the document — or can only point at via a rejected,
       unreliable candidate — cannot be "medium".
    2. HIGH — passed the gate, matched a table CELL (the finest-grained
       provenance the product can offer), the value parsed into its target
       type cleanly, and — for sub-limits — the basis wasn't read off a
       header the source PDF had merged/duplicated across columns
       (SPIKE_NOTES.md finding 4).
    3. MEDIUM — passed the gate but matched a text item rather than a cell
       (most waiting-period and exclusion facts are only ever stated in
       prose, never in a table — see SPIKE_NOTES.md finding 2, so this is
       the honest ceiling for those fields, not a defect), OR the value
       needed coercion, OR the basis came from a spanned/duplicated header.

    Note what's *not* here any more: a raw fuzzy-score threshold no longer
    distinguishes "high" from "medium" for a cell match. Before Fix 1, a
    weak-but-passing cell match was capped at "medium" as a hedge against
    exactly the false-match failure mode this file now guards against
    directly (length, bbox size, value containment, token overlap all
    checked before a candidate is even scored) — with that gate in place,
    any cell match that survives it has already been verified to actually
    contain the right value in a real cell, so there's nothing left for a
    score threshold to hedge against. Keeping both would just double-count
    the same risk under two different names.

    Confidence is computed here rather than asked of the model because it
    is a property of *how the value was matched back into the document* —
    something the model has no visibility into (it doesn't know whether
    the sentence it quoted also appears, word for word, in a table cell
    three pages away). A model-reported confidence field would also invite
    the model to conflate "I'm sure this is what the document says" with
    "this figure is favourable" or "I recall this being typical for
    Indian health policies" — a different question, and one a JSON schema
    field cannot force it to answer honestly. A confidence computed from
    match geometry has no such failure mode: it is reproducible from the
    same inputs every time, which is the property this makes defensible.
    """
    if not value_is_present or match.matched_via == "none":
        return "low"
    if match.matched_via == "cell" and value_parsed_cleanly and not basis_from_spanned_header:
        return "high"
    return "medium"


def is_spanned_header_column(table: TableRecord, matched_cell: TableCellRecord) -> bool:
    """True if the column header governing matched_cell's column shares its
    exact (normalised) text with another column's header in the same table.

    This is the concrete, checkable signature of SPIKE_NOTES.md finding 4:
    a merged header cell in the source PDF is exploded into duplicate text
    across every column it spans in Docling's table export. A basis word
    ("per day") read from such a header is context, not a reliable
    per-column label, so callers use this to route the affected sub-limit
    to "medium" instead of "high" even on an otherwise strong cell match.
    """
    header_texts_by_column: dict[int, str] = {}
    for cell in table.cells:
        if cell.column_header:
            header_texts_by_column[cell.start_col_offset_idx] = _normalise_for_match(cell.text)

    this_column_text = header_texts_by_column.get(matched_cell.start_col_offset_idx)
    if not this_column_text:
        return False

    duplicate_count = sum(1 for text in header_texts_by_column.values() if text == this_column_text)
    return duplicate_count > 1
