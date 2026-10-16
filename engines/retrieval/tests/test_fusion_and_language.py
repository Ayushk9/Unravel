from engines.retrieval.fusion import reciprocal_rank_fusion
from engines.retrieval.language import ascii_digits, has_devanagari, normalise_question


def test_an_item_high_in_both_lists_beats_one_top_in_only_one() -> None:
    dense = ["a", "b", "c"]
    sparse = ["b", "d", "a"]

    fused = [item for item, _ in reciprocal_rank_fusion([dense, sparse])]

    assert fused[0] == "b"  # 1/62 + 1/61 beats "a": 1/61 + 1/63
    assert fused[:2] == ["b", "a"]
    assert set(fused) == {"a", "b", "c", "d"}


def test_fusion_scores_are_the_rrf_formula() -> None:
    fused = dict(reciprocal_rank_fusion([["x"], ["y", "x"]]))

    assert fused["x"] == 1 / 61 + 1 / 62
    assert fused["y"] == 1 / 61


def test_ties_are_broken_by_first_appearance() -> None:
    fused = [item for item, _ in reciprocal_rank_fusion([["p", "q"], ["q", "p"]])]

    assert fused == ["p", "q"]


def test_empty_lists() -> None:
    assert reciprocal_rank_fusion([[], []]) == []


def test_devanagari_detection_and_digits() -> None:
    assert has_devanagari("क्या मेरा कमरा कवर है?")
    assert has_devanagari("माझी पॉलिसी")  # Marathi, same script
    assert not has_devanagari("What if I choose a room?")
    assert ascii_digits("₹१२,००० प्रति दिन") == "₹12,000 प्रति दिन"


def test_normalised_question_folds_case_space_and_digits() -> None:
    assert normalise_question("  What if   I choose a ₹१२,००० ROOM? ") == "what if i choose a ₹12,000 room?"
    assert normalise_question("room rent 5,000") != normalise_question("room rent 5000")
