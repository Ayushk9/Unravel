"""Exceptions raised by the Engine A extraction pipeline."""

from __future__ import annotations


class ExtractionError(Exception):
    """Raised when parse_and_extract cannot produce a usable result.

    Reserved for unrecoverable failures: the file can't be parsed at all,
    the LLM call fails after retries, or the response fails schema
    validation. A field the model or provenance matcher simply couldn't
    resolve is not an ExtractionError — it comes back as
    Extracted(value=None, confidence="low", provenance=None) with a note in
    ExtractionResult.warnings, per the task's failure-behaviour rules.
    """
