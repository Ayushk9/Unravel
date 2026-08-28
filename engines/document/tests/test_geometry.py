"""Unit tests for normalise_bbox, using real numbers captured from Docling
runs against engines/document/samples/dev_policy_synthetic.pdf (page 1,
595.2756 x 841.8898 pt — A4, matching SPIKE_NOTES.md), not synthetic
round-number coordinates. See SPIKE_NOTES.md finding 2 for why both origins
must be exercised.
"""

from __future__ import annotations

import warnings

import pytest
from docling_core.types.doc.base import BoundingBox, CoordOrigin

from geometry import normalise_bbox

PAGE_W = 595.2756
PAGE_H = 841.8898


def test_bottomleft_text_item_real_numbers() -> None:
    # Real text-item prov bbox: page-1 title of dev_policy_synthetic.pdf.
    bbox = BoundingBox(
        l=48.51969,
        t=787.4123528,
        r=513.2569955,
        b=774.4123528,
        coord_origin=CoordOrigin.BOTTOMLEFT,
    )

    x0, y0, x1, y1 = normalise_bbox(bbox, PAGE_W, PAGE_H)

    assert x0 == pytest.approx(0.08150794354749295)
    assert y0 == pytest.approx(0.0647085250349868)
    assert x1 == pytest.approx(0.8622174258444324)
    assert y1 == pytest.approx(0.08014997592321468)


def test_topleft_table_cell_real_numbers() -> None:
    # Real table_cells[].bbox: page-1 "Policy Number" cell of the same file.
    bbox = BoundingBox(
        l=63.11024,
        t=99.656158,
        r=244.22173474999994,
        b=107.156158,
        coord_origin=CoordOrigin.TOPLEFT,
    )

    x0, y0, x1, y1 = normalise_bbox(bbox, PAGE_W, PAGE_H)

    assert x0 == pytest.approx(0.10601852318489115)
    assert y0 == pytest.approx(0.11837197457434454)
    assert x1 == pytest.approx(0.4102666642980158)
    assert y1 == pytest.approx(0.12728050393293755)


def test_bottomleft_y_is_not_topleft_y() -> None:
    # A regression guard against the exact mirroring bug finding 2 warns
    # about: for a BOTTOMLEFT bbox in the top half of the page (large t, b),
    # normalised y must come out small (near the top), not large.
    bbox = BoundingBox(l=0, t=800, r=100, b=790, coord_origin=CoordOrigin.BOTTOMLEFT)

    _, y0, _, y1 = normalise_bbox(bbox, PAGE_W, PAGE_H)

    assert y0 < 0.1
    assert y1 < 0.1
    assert y0 < y1


def test_full_page_bbox_hits_exact_bounds() -> None:
    bbox = BoundingBox(l=0, t=PAGE_H, r=PAGE_W, b=0, coord_origin=CoordOrigin.BOTTOMLEFT)

    x0, y0, x1, y1 = normalise_bbox(bbox, PAGE_W, PAGE_H)

    assert (x0, y0, x1, y1) == pytest.approx((0.0, 0.0, 1.0, 1.0))


def test_unknown_coord_origin_raises() -> None:
    bbox = BoundingBox(l=0, t=10, r=10, b=0, coord_origin=CoordOrigin.BOTTOMLEFT)
    object.__setattr__(bbox, "coord_origin", "DIAGONAL")  # force an invalid value past validation

    with pytest.raises(ValueError, match="unknown coord_origin"):
        normalise_bbox(bbox, PAGE_W, PAGE_H)


def test_marginal_overflow_clamps_with_warning() -> None:
    # 0.0001pt past the page edge — float noise, not a real error.
    bbox = BoundingBox(l=-0.0001, t=PAGE_H, r=PAGE_W, b=0, coord_origin=CoordOrigin.BOTTOMLEFT)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        x0, _, _, _ = normalise_bbox(bbox, PAGE_W, PAGE_H)

    assert x0 == 0.0
    assert len(caught) == 1
    assert "marginally outside" in str(caught[0].message)


def test_wild_overflow_raises() -> None:
    # Way past the page edge — e.g. bbox matched against the wrong page's
    # dimensions. This must be a hard failure, not a silently clamped value.
    bbox = BoundingBox(l=0, t=PAGE_H * 3, r=PAGE_W, b=0, coord_origin=CoordOrigin.BOTTOMLEFT)

    with pytest.raises(ValueError, match="far outside"):
        normalise_bbox(bbox, PAGE_W, PAGE_H)


def test_non_positive_page_dimensions_raise() -> None:
    bbox = BoundingBox(l=0, t=10, r=10, b=0, coord_origin=CoordOrigin.BOTTOMLEFT)

    with pytest.raises(ValueError, match="page dimensions must be positive"):
        normalise_bbox(bbox, 0.0, PAGE_H)
