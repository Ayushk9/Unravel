"""Base class for every request and response model defined by the API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """snake_case fields exactly as declared, and no undeclared fields.

    Pydantic serialises a field whose value is None as `null` by default,
    which is what API_DECISIONS D-05 requires. The ways to switch that off
    (`exclude_none`, `exclude_unset`, `exclude_defaults`) must never be used;
    tests/test_serialisation.py checks every registered route for them.
    """

    model_config = ConfigDict(extra="forbid")
