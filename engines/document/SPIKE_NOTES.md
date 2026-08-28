# Engine A — Docling capability spike

Date: 2026-08-27. Docling 2.123.0 (already installed in `.venv`, PyTorch 2.13.0,
CPU). No extraction logic, no LLM calls — this is purely "what does the parser
give us." Scripts: `scripts/spike_parse.py`, `scripts/spike_report.py`. Raw
output per PDF lives in `out/{pdf_stem}/` (gitignored, not committed).

Ran against three real Star Comprehensive documents in `samples/`. (`samples/`
also has `dev_policy_synthetic.pdf` and `warmup.pdf` — small synthetic/warm-up
fixtures, not part of this spike's "three PDFs"; `warmup.pdf` was used to
sanity-check the scripts before the real runs, see below.)

| File | Kind | Pages |
| --- | --- | --- |
| `Policy_Star_Comprehensive_Insurance_Policy_V_21_3a414ab104.pdf` | digital-born policy wording | 48 |
| `Prospectus_Star_Comprehensive_Insurance_Policy_V_12_dc6058c95e.pdf` | digital-born prospectus | 53 |
| `policy_star_senior_citizens_SCANNED.pdf` | scanned policy | 32 |

---

## Policy_Star_Comprehensive (digital)

**Sub-limits table** survived as a real table, not prose. `tables/table_1_page_10.csv`
(9 rows × 7 cols) and `table_2_page_10.csv` (9 rows × 5 cols):

```
"5,00,000/-","1,25,000/-","50,000/-","2,50,000/-","1,25,000/-","2,50,000/-","50,000/-"
"7,50,000/-","1,25,000/-","50,000/-","2,50,000/-","1,25,000/-","2,75,000/-","60,000/-"
"10,00,000/-","1,50,000/-","1,00,000/-","3,00,000/-","2,00,000/-","4,00,000/-","75,000/-"
```

Note the CSV has **no header row** — the column labels ("Sum Insured on
Individual Basis", "Room Rent", etc.) are separate `TextItem`s positioned
above the table in the source, not baked into row 0 of the table data. A
consumer has to associate them by proximity/reading order, not by CSV header.

**Waiting periods**: findable, but in **prose**, not a table. Pre-existing
diseases: "excluded until the expiry of 36 months of continuous coverage
after the date of inception" (full_document.md line 929), with a buy-back
option down to 12 months described separately (line 883). Specific waiting
period (36 months) is defined in the glossary (line 187) then applied again
in the exclusions section — the same fact appears in the document at least
twice, in different wording.

**Sum insured**: findable throughout, both as a defined term (glossary) and
as the row-key of the sub-limits table above.

Parse time: 200.7s / 48 pages = 4.18s/page.

---

## Prospectus_Star_Comprehensive (digital)

**Sub-limits**: same pattern — real tables (33 detected). But here the header
row problem is worse: merged header cells in the source get **exploded into
duplicate text per column** rather than a single spanning cell:

```
| Sum Insured (Rs.) | Uterine artery Embolization and HIFU | Balloon Sinuplasty | ... |
| Sum Insured (Rs.) | Sum Insured on Individual Basis : Limit per person... | Sum Insured on Individual Basis : Limit per person... | ... |
```

Both rows repeat "Sum Insured (Rs.)" / the same long limit-basis sentence
across every column — that's one merged cell in the PDF, six identical text
values in Docling's table export. Any downstream table-to-field mapping has
to de-duplicate this, not trust that distinct cells mean distinct labels.

**Waiting periods / sum insured**: same as above — prose-based, glossary +
exclusions, sum insured also present as sub-limit table row-keys.

Parse time: 285.9s / 53 pages = 5.4s/page — slower per-page than the shorter
digital doc despite also being digital-born; more tables (33 vs 24) is the
likely driver, table-structure recognition is the expensive step.

---

## policy_star_senior_citizens_SCANNED (scanned)

Room rent sub-limit **did** survive as a table, via OCR:

```
| Sum Insured                     | Room Rent Limit (per day)  |
| Rs.1,00,000/- to Rs.5,00,000/-  | Up tol% of the Sum Insured |
```

`"Up tol%"` — OCR misread "1" as "l". This is the headline risk of the
scanned path: the *structure* (rows/columns) survives, but individual
**characters inside numeric/percentage values are not guaranteed correct**,
and a wrong "1" vs "l" would silently corrupt a room-rent cap if trusted
without a human check.

Also observed OCR dropping spaces between words in places: `"Renewal:Renewalmeansthetermsonwhich"`
in the glossary (full_document.md line 154) — cosmetic in prose, but the same
failure mode applied to a number (`"1,00,000"` reading as `"100,000"` or
similar) would be a silent, unflagged extraction error.

Pre-existing-disease waiting period language is present and readable via OCR,
same 36-month prose pattern as the digital documents.

Parse time: 177.7s / 32 pages = 5.55s/page — **not** dramatically slower
per-page than the digital documents (4.18–5.4s/page). OCR did not blow up
wall-clock time the way I expected going in; table-structure recognition
seems to dominate the cost more than text-recognition mode does.

---

## Cross-cutting findings

- **Bboxes and page dimensions exist for every text item, in every
  document, including the scanned one** — 852 + 553 + 603 = 2,008 text items
  checked, zero missing bboxes.
- **Page number indexing: 1-indexed.** Confirmed by cross-checking
  `ProvenanceItem.page_no` against the keys of `doc.pages` — they match
  exactly (page 1 is `doc.pages[1]`, not `doc.pages[0]`). Not converted
  anywhere in the spike scripts.
- **Bbox coordinate origin: bottom-left**, consistently, across all three
  documents (`CoordOrigin.BOTTOMLEFT`), including the OCR'd scanned one. No
  per-item variation observed. Fields are named `l, t, r, b` but because the
  origin is bottom-left, `t` (top) is the numerically *larger* y-value and
  `b` (bottom) the smaller — easy to get backwards if you assume top-left
  convention by habit.
- **Surprise — scanned-page geometry is normalised to standard PDF point
  space, not pixel space.** `policy_star_senior_citizens_SCANNED.pdf`'s
  `pages.json` reports the same `595.276 × 841.89` (A4 in points) as the two
  digital documents, not the scan's raw pixel dimensions. Docling appears to
  wrap OCR output back into a synthetic point-based page geometry, so
  downstream bbox-normalisation code does not need a separate code path for
  scanned vs digital sources — one coordinate convention for both.
- **`ocr_appeared_needed: true` fired on *all three* documents**, including
  the two nominally "digital-born" ones. This is the single biggest surprise
  of the spike. It means either (a) these "digital" policy PDFs have at
  least one embedded scanned/image page (e.g. a signature page, stamp, or
  annexure — common in Indian insurer PDFs) that triggered OCR on just that
  page, or (b) the detection heuristic (see below) is being triggered by
  something other than true OCR use. **Not resolved in this spike** — the
  stats.json only records a document-level boolean, not which pages
  triggered it. Worth a per-page breakdown before trusting this signal for
  anything real.
- The OCR-needed detector itself is a heuristic, not a Docling-reported
  fact: it reads `confidence.pages[n].ocr_score`, which is `NaN` when OCR
  did not run on that page and a real float when it did. This is documented
  inline in `stats.json`'s `ocr_detection_note` field and should be treated
  as approximate.
- No PDF failed to parse; all three plus `warmup.pdf` returned
  `ConversionStatus.SUCCESS` with zero Docling-reported errors.

---

## Implications for C-2

1. **Prompting the LLM**: hand it the CSV table plus the preceding text
   items (by page + reading order), not the table in isolation — column
   headers frequently live outside the table structure, and merged-cell
   headers can appear duplicated inside it. The LLM needs both to resolve
   what a bare numeric column actually means.

2. **Waiting periods and similar clause-level facts will not come from a
   table.** They're prose, often stated more than once in different
   wording (glossary vs. exclusions). Retrieval/extraction for these fields
   needs to search across the whole document and reconcile duplicates, not
   assume a single canonical location.

3. **Provenance recovery is straightforward for text-item-level facts**:
   every text item already carries `(page_no, bbox)`, 1-indexed page,
   bottom-left origin, in PDF-point units consistent across digital and
   scanned sources. The extraction layer should carry these three values
   through untouched from Docling's raw output to the `Provenance` object —
   no coordinate-system branching needed for scanned vs digital.

4. **Table-cell-level provenance is the open problem.** `TableItem.prov`
   gives one bbox for the *whole table*, not per-cell. If a UI needs to
   highlight the specific cell a number came from (not just "somewhere in
   this table on this page"), that requires either Docling's cell-level
   geometry (need to check `TableData`/`TableCell` for per-cell bbox in a
   follow-up spike) or falls back to table-level provenance only, which is
   a coarser but still honest claim.

5. **Scanned-document numeric values need a trust discount.** OCR
   preserved table *structure* correctly in the one scanned sample tested,
   but character-level errors in numbers (`1`→`l`) are real and silent —
   Docling does not flag low-confidence characters inline in the text
   content, only an aggregate per-page `ocr_score`. Any extracted value
   whose source page has a low `ocr_score` should probably render at a
   lower confidence tier by default, and/or get flagged for the "sourced
   from OCR — verify against the original" treatment the product already
   has for other low-confidence cases, rather than being trusted at face
   value the way a digital-PDF extraction would be.

6. **Investigate the "ocr_appeared_needed on digital PDFs" result** before
   building anything that branches behavior on it (e.g. routing to a
   different confidence tier by source type) — right now it's not clear
   whether that signal means "one annexure page was scanned" or "the
   heuristic is noisy." A per-page ocr_score dump (cheap: `stats.json`
   already has the aggregate, per-page just needs including) would resolve
   this before it becomes load-bearing anywhere.

7. **`Policy_Star_Comprehensive`'s actual sum insured is not in this
   document at all — confirmed 2026-08-29, engine build, Fix 4.** Every
   occurrence of "Sum Insured" in `full_document.md` and in the sub-limit
   band tables (`table_2_page_10.csv` etc.) is either a glossary
   definition ("Basic Sum Insured means...") or a table row-key spanning
   the product's whole tier range — ₹5,00,000 through ₹1,00,00,000 — used
   to look up *other* sub-limits by band, never a standalone stated figure
   for *this* policyholder. That number lives in the Policy Schedule, a
   separate document this spike has no sample of (the schedule is
   typically a 1-2 page cover sheet issued per-policyholder, distinct from
   the wordings/prospectus PDFs sampled here). Same root cause likely
   explains why `room_rent` and `icu` sub-limits are absent too (see the
   Engine A build notes, Fix 2) — this specific policy grants a fixed room
   *category* ("Private Single A/C Room") rather than a rupee room-rent
   cap, so there is no number there to extract either. Do not treat either
   absence as an extraction bug without checking against a real Schedule
   sample first.
