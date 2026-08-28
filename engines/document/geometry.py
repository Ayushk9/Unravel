"""Docling bbox -> normalised, TOPLEFT-origin coordinates for pdf.js.

Docling emits two coordinate systems in the *same* converted document (see
SPIKE_NOTES.md finding 2): text items and whole-table `prov` bboxes use
BOTTOMLEFT origin, while per-cell `table_cells[].bbox` uses TOPLEFT origin.
Every bbox object carries its own `coord_origin` field — this module trusts
that field on every call and never assumes one convention for a given source
type. Getting this wrong produces coordinates that are numerically valid but
vertically mirrored, which renders as a plausible-looking highlight in the
wrong place on the page and is not caught by any type check.
"""

from __future__ import annotations

import warnings

from docling_core.types.doc.base import BoundingBox, CoordOrigin

# How far outside [0, 1] an output coordinate may fall before we treat it as
# float rounding noise (clamp + warn) rather than a real bug (raise). 1e-3 is
# generously larger than any float64 accumulation error from the divisions
# below, so anything past it means the input bbox itself is wrong — e.g. a
# bbox from the wrong page's dimensions — not just a rounding artifact.
_CLAMP_EPSILON = 1e-3


def normalise_bbox(
    bbox: BoundingBox,
    page_width: float,
    page_height: float,
) -> tuple[float, float, float, float]:
    """Convert a Docling bbox to normalised (x0, y0, x1, y1), TOPLEFT origin, 0..1.

    Reads `bbox.coord_origin` rather than assuming one convention — see the
    module docstring. Raises on an unrecognised origin instead of guessing,
    because a silent wrong guess here is invisible in the output JSON: the
    numbers still look like plausible coordinates, just mirrored.
    """
    if page_width <= 0 or page_height <= 0:
        raise ValueError(
            f"page dimensions must be positive, got width={page_width}, height={page_height}"
        )

    x0 = bbox.l / page_width
    x1 = bbox.r / page_width

    if bbox.coord_origin == CoordOrigin.BOTTOMLEFT:
        # Docling's `t` (top) is the numerically larger y in a bottom-left
        # system, and `b` (bottom) the smaller one — flipping which of t/b
        # maps to y0 here is the exact mistake finding 2 warns about.
        y0 = (page_height - bbox.t) / page_height
        y1 = (page_height - bbox.b) / page_height
    elif bbox.coord_origin == CoordOrigin.TOPLEFT:
        y0 = bbox.t / page_height
        y1 = bbox.b / page_height
    else:
        raise ValueError(f"unknown coord_origin: {bbox.coord_origin!r}")

    return tuple(
        _clamp_unit(value, label=label) for value, label in zip((x0, y0, x1, y1), ("x0", "y0", "x1", "y1"))
    )  # type: ignore[return-value]


def _clamp_unit(value: float, *, label: str) -> float:
    if 0.0 <= value <= 1.0:
        return value

    overflow = -value if value < 0.0 else value - 1.0
    if overflow > _CLAMP_EPSILON:
        raise ValueError(
            f"normalised {label}={value!r} is far outside [0, 1] "
            f"(overflow={overflow!r}) — likely wrong page dimensions or bbox"
        )

    clamped = 0.0 if value < 0.0 else 1.0
    warnings.warn(
        f"normalised {label}={value!r} was marginally outside [0, 1] "
        f"(overflow={overflow!r}); clamped to {clamped}",
        stacklevel=3,
    )
    return clamped
