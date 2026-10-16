from engines.retrieval.verify import NUMBER_REASON, SUPPORT_REASON, Sentence, assemble, decide, precheck

CHUNKS = {
    "c1": "Room rent: up to Rs 5,000 per day",
    "c2": "Pre-existing diseases: covered after 48 months of continuous coverage",
    "c3": "Cosmetic or aesthetic treatment is excluded",
}
QUESTION = "What if I choose a ₹12,000/day room?"


def test_precheck_removes_a_wrong_number_before_any_judging() -> None:
    good = Sentence("Your room rent is capped at ₹5,000 per day.", ("c1",))
    bad = Sentence("Your room rent is capped at ₹10,000 per day.", ("c1",))

    passed, removed = precheck([good, bad], CHUNKS, QUESTION)

    assert passed == [good]
    assert [(r.sentence, r.reason) for r in removed] == [(bad, NUMBER_REASON)]


def test_a_sentence_survives_only_with_a_supporting_citation() -> None:
    supported = Sentence("Your room rent is capped at ₹5,000 per day.", ("c1", "c3"))
    unsupported = Sentence("Cosmetic surgery is covered.", ("c3",))

    outcome = decide([supported, unsupported], {(0, "c1"): True, (0, "c3"): False, (1, "c3"): False}, CHUNKS, QUESTION, [])

    assert outcome.kept == [Sentence(supported.text, ("c1",))], "the rejected citation is dropped"
    assert [(r.sentence, r.reason) for r in outcome.removed] == [(unsupported, SUPPORT_REASON)]
    assert outcome.checked == 2


def test_a_missing_verdict_counts_as_unsupported() -> None:
    sentence = Sentence("Your room rent is capped at ₹5,000 per day.", ("c1",))

    outcome = decide([sentence], {}, CHUNKS, QUESTION, [])

    assert outcome.kept == [] and outcome.removed[0].reason == SUPPORT_REASON


def test_numbers_are_rechecked_against_the_clauses_that_survive() -> None:
    # The 48 months is only in c2, but only c1 is judged to support the sentence.
    sentence = Sentence("Room rent is capped at ₹5,000 per day and the waiting period is 48 months.", ("c1", "c2"))

    outcome = decide([sentence], {(0, "c1"): True, (0, "c2"): False}, CHUNKS, QUESTION, [])

    assert outcome.kept == [] and outcome.removed[0].reason == NUMBER_REASON


def test_nothing_supported_leaves_nothing_to_say() -> None:
    sentence = Sentence("Cosmetic surgery is covered.", ("c3",))

    outcome = decide([sentence], {(0, "c3"): False}, CHUNKS, QUESTION, [])

    assert outcome.kept == []


def test_assemble_numbers_citations_in_order_and_reuses_them() -> None:
    kept = [
        Sentence("Room rent is capped at ₹5,000 per day.", ("c1",)),
        Sentence("Pre-existing diseases wait 48 months.", ("c2", "c1")),
    ]

    text, order = assemble(kept)

    assert order == ["c1", "c2"]
    assert text == "Room rent is capped at ₹5,000 per day. [[1]] Pre-existing diseases wait 48 months. [[2]][[1]]"
