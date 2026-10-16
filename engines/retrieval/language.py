"""Small text helpers for questions in English, Hindi and Marathi.

Hindi and Marathi are both written in Devanagari, so the script is enough to
know the question is not English. Which of the two it is does not matter
here: the rewrite into English search terms handles both.
"""

from __future__ import annotations

import re
import unicodedata

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
# ० १ २ ३ ४ ५ ६ ७ ८ ९  ->  0 1 2 3 4 5 6 7 8 9
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def has_devanagari(text: str) -> bool:
    return _DEVANAGARI.search(text) is not None


def ascii_digits(text: str) -> str:
    """Devanagari digits to ASCII, so "₹१२,०००" reads as "₹12,000" everywhere downstream."""
    return text.translate(_DEVANAGARI_DIGITS)


def normalise_question(question: str) -> str:
    """The form used for the cache key: the same question typed slightly differently is the same key.

    NFKC folds look-alike characters (full-width digits, compatibility forms);
    then digits are made ASCII, case is folded, and whitespace is collapsed.
    Punctuation is kept: "room rent?" and "room rent" are close enough to
    share an answer, but stripping punctuation would also merge "5,000" and "5000".
    """
    text = ascii_digits(unicodedata.normalize("NFKC", question))
    return " ".join(text.casefold().split())
