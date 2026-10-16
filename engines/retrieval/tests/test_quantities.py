import pytest

from engines.retrieval.quantities import Quantity, extract_quantities, missing_numbers


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("₹5,000", Quantity("money", "500000")),
        ("Rs. 5000/-", Quantity("money", "500000")),
        ("Rs 5,00,000", Quantity("money", "50000000")),
        ("5 lakh", Quantity("money", "50000000")),
        ("Rs 1.5 crore", Quantity("money", "1500000000")),
        ("INR 750", Quantity("money", "75000")),
        ("10%", Quantity("percent", "10")),
        ("10 per cent", Quantity("percent", "10")),
        ("48 months", Quantity("months", "48")),
        ("4 years", Quantity("months", "48")),
        ("30 days", Quantity("days", "30")),
        ("24 hours", Quantity("hours", "24")),
        ("Section 4.2", Quantity("number", "4.2")),
        ("₹१२,०००", Quantity("money", "1200000")),
    ],
)
def test_each_kind_of_number_is_normalised(text: str, expected: Quantity) -> None:
    assert extract_quantities(text) == {expected}


def test_rs_inside_a_word_is_not_a_rupee_sign() -> None:
    assert extract_quantities("within 24 hrs 3 times") == {Quantity("hours", "24"), Quantity("number", "3")}


def test_the_brief_case_a_different_amount_is_unsupported() -> None:
    missing = missing_numbers("Your policy pays up to ₹10,000 per day for room rent.", ["Room rent: up to Rs 5,000 per day"])

    assert missing == [Quantity("money", "1000000")]


def test_the_same_amount_written_differently_is_supported() -> None:
    assert missing_numbers("Room rent is capped at ₹5,000 a day.", ["Room rent shall not exceed Rs. 5000/- per day"]) == []


def test_an_amount_without_a_currency_mark_in_the_clause_still_matches() -> None:
    assert missing_numbers("The cap is ₹5,000 per day.", ["Room rent limit 5000 per day"]) == []


def test_years_and_months_are_the_same_period() -> None:
    assert missing_numbers("Pre-existing diseases are covered after 4 years.", ["covered after 48 months of continuous coverage"]) == []


def test_days_are_never_turned_into_months() -> None:
    assert missing_numbers("The initial waiting period is 1 month.", ["Initial waiting period of 30 days"]) == [Quantity("months", "1")]


def test_percentages_must_match() -> None:
    assert missing_numbers("A 20% co-payment applies.", ["Co-payment: 10% of admissible claim amount"]) == [Quantity("percent", "20")]
    assert missing_numbers("A 10% co-payment applies.", ["Co-payment: 10% of admissible claim amount"]) == []


def test_lakh_in_the_sentence_matches_digits_in_the_clause() -> None:
    assert missing_numbers("Your sum insured is ₹5 lakh.", ["Sum Insured: Rs. 5,00,000"]) == []


def test_a_number_from_the_question_is_allowed_when_passed_as_a_source() -> None:
    sentence = "A ₹12,000/day room is above your ₹5,000 per day room rent limit."
    clause = "Room rent: up to Rs 5,000 per day"

    assert missing_numbers(sentence, [clause]) == [Quantity("money", "1200000")]
    assert missing_numbers(sentence, [clause, "What if I choose a ₹12,000/day room?"]) == []


def test_a_computed_difference_is_not_allowed() -> None:
    sentence = "You would pay ₹7,000 a day yourself."
    sources = ["Room rent: up to Rs 5,000 per day", "What if I choose a ₹12,000/day room?"]

    assert missing_numbers(sentence, sources) == [Quantity("money", "700000")]


def test_a_sentence_with_no_numbers_passes() -> None:
    assert missing_numbers("Cosmetic treatment is excluded.", ["Cosmetic or aesthetic treatment is excluded"]) == []


def test_numbers_written_as_words_are_not_read() -> None:
    # The prompt asks for digits; a clause in words cannot vouch for a digit sentence.
    assert missing_numbers("The period is 30 days.", ["a period of thirty days"]) == [Quantity("days", "30")]
