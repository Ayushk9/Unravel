/**
 * Task 3 hardening: `ProvenanceChip` -> `DocumentViewer` is the demo's
 * signature interaction, and a WRONG highlight is worse than NO highlight —
 * it launders a bad extraction as verified. Every check here is deliberately
 * conservative: any doubt degrades to a plain page-level jump (or, if the
 * page itself is unusable, no navigation at all), never a best-effort guess
 * at what the extractor "probably meant."
 */
import type { Provenance } from "@/api/types";

export interface BboxValidation {
  valid: boolean;
  /** Only set when bbox is present but malformed — never set for "no bbox", which is a normal, expected state, not a bug to report. */
  reason?: string;
}

/** bbox convention (DocumentViewer): [x0, y0, x1, y1], normalised 0..1, top-left origin. */
export function validateBbox(bbox: Provenance["bbox"]): BboxValidation {
  if (bbox == null) {
    return { valid: false };
  }
  const [x1, y1, x2, y2] = bbox;
  const components = [x1, y1, x2, y2];
  if (components.some((v) => !Number.isFinite(v) || v < 0 || v > 1)) {
    return { valid: false, reason: `bbox component outside 0..1: [${bbox.join(", ")}]` };
  }
  if (x2 <= x1 || y2 <= y1) {
    return { valid: false, reason: `inverted or zero-area bbox: [${bbox.join(", ")}]` };
  }
  return { valid: true };
}

/** Structural check only — a page number that's finite, whole, and at least 1. Doesn't need `page_count` (see validatePageAgainstCount for the check that does). */
export function isPageNumberUsable(page: number): boolean {
  return Number.isFinite(page) && Number.isInteger(page) && page >= 1;
}

export interface PageValidation {
  valid: boolean;
  reason?: string;
}

/** The fuller check, used once `page_count` is actually known (DocumentViewer, after the PDF loads). */
export function validatePageAgainstCount(page: number, pageCount: number | null | undefined): PageValidation {
  if (!isPageNumberUsable(page)) {
    return { valid: false, reason: `page ${page} is not a usable page number` };
  }
  if (pageCount != null && page > pageCount) {
    return { valid: false, reason: `page ${page} exceeds the document's ${pageCount} pages` };
  }
  return { valid: true };
}

/** So the extraction side can be told which field is broken — never logged for "no bbox"/"no page_count yet", only for genuinely malformed data. */
export function logRejectedProvenance(provenance: Provenance, reason: string): void {
  if (import.meta.env.DEV) {
    console.warn("[provenance] rejected, degrading:", reason, provenance);
  }
}
