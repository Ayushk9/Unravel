# Design direction

Status: tokens and primitives both shipped in Phase 1. `<Money>`, `<ProvenanceChip>`,
`<ConfidenceBadge>`, `<VerdictBand>`, `<DeadlineCard>`, `<CitationList>`,
`<DocumentViewer>`, and the loading/empty/error/abstention primitives all render at
`/kitchen-sink` in every state they can occupy — that page is the living source of
truth for this document, not the other way around.

## Why this direction

The subject is money, documents, deadlines, and evidence, not health or finance in the
abstract. The visual language comes from **the policy document itself** — page edges,
clause numbering, tabular ledgers, stamps, ticket-stub perforations — not from fintech
gradients, medical iconography, or a generic "AI product" look.

Explicitly avoided: cream `#F4F1EA` + high-contrast serif + terracotta; near-black +
single acid accent; broadsheet hairline-rule layouts; shadcn's out-of-the-box
slate-and-blue.

## Tokens

Six foundational hex values, plus two semantic accents finalised in Phase 1 to
complete a single four-tone state system reused everywhere: eligibility bands,
confidence tiers, provenance state, deadline urgency, flag severity. Every one of
those pairs a tone with an icon and a text label — colour is never the only cue
(verified in `/kitchen-sink` with a greyscale screenshot).

| Token | Hex | Role |
| --- | --- | --- |
| `--paper` | `#ECEFE9` | Page background — a pale ledger grey-green, not cream |
| `--ink` | `#1C2420` | Primary text — deep charcoal-green, not pure black |
| `--ink-muted` | `#5B685F` | Secondary text, captions, muted labels |
| `--rule` | `#C7CFC2` | Hairline borders, table rules, dividers |
| `--stamp` | `#1F5E4A` | **Positive** — verified, eligible, satisfied, confirmed. Ink-stamp green |
| `--flag` | `#AE3A2C` | **Negative** — errors, ineligible, failed, critical. Rejection-stamp red-oxide |
| `--caution` | `#7A5C18` | **Caution** — at-risk, medium confidence, unconfirmed, due-soon. Ledger-pencil amber |
| `--neutral` | `#2B5470` | **Neutral/informational** — insufficient information, abstention, unknown. Deliberately *not* red: abstention is a normal state (product rule 3), so it never borrows the negative tone |

All four text colours are ≥4.5:1 contrast against both `--paper` and the `--card`
surface (`#F5F6F2`) — checked, not eyeballed. Each tone also has a `-bg`/`-border`
pair (`color-mix()` tints of the tone into `--paper`) for filled badges and bands, so
a state reads as a stamped tint on the page rather than a saturated fintech pill.

### Provenance is three states, not two

`<ProvenanceChip>` turned out to need three states once built, not the two this
document originally sketched — product rule 1 ("missing provenance is always
unverified, never confirmed") and the brief's own review-screen behaviour ("a policy
can be saved with unconfirmed fields, but those fields carry the unverified treatment
downstream") don't collapse into one "unverified" bucket without losing information:

- **verified** — has provenance *and* `user_confirmed`. Filled, stamp-toned.
- **unconfirmed** — has provenance, not yet confirmed. Dashed outline, caution-toned,
  still clickable so the user can go check it.
- **unverified** — no provenance at all. Dashed outline, neutral-toned, not
  clickable — there's nothing to open, and it can never render as confirmed.

### `<Money>` compact threshold

Below ₹1,00,000, `compact` shows the same full amount (no shorter form is worth it).
₹1,00,000–₹99,99,999 shows `₹X.XXL`. ₹1,00,00,000 and above shows `₹X.XXCr`.

### `<DocumentViewer>` bbox convention

`Provenance.bbox` is `[x0, y0, x1, y1]`, normalised 0..1, **top-left origin** (y grows
downward — screen/image space, not PDF's native bottom-left origin). The highlight
overlay is positioned in percentages of the rendered page box, not computed pixels,
so it tracks react-pdf's layout exactly regardless of container width. Verified
against a hand-built two-page fixture PDF with a known bbox — the highlight landed
correctly on the first attempt, so no fallback to page-only jump was needed this
phase. When a Provenance has no bbox, the viewer still jumps to the page and shows a
banner saying an exact location isn't available, rather than drawing a wrong box.

## Typefaces

Two families, both from the IBM Plex superfamily — chosen because Plex was designed
for forms, technical documents, and dense tabular data, which is exactly this
product's material.

- **IBM Plex Sans** — UI text, body copy, labels, navigation. Role: the voice of the
  product explaining things in plain language.
- **IBM Plex Serif** — headings and section titles only. Low-contrast, restrained
  (not the "high-contrast serif" look the brief warns off). Role: marks something as
  belonging to a document register, not a marketing register.
- **IBM Plex Mono** (`font-variant-numeric: tabular-nums`) — every number: money,
  clause references, dates, page numbers, ids. Role: the ledger voice. This is what
  makes columns of rupee amounts and clause numbers actually line up, and it is the
  one typographic signal that appears everywhere a fact is being cited rather than
  described.

### Type scale

| Step | Size / line-height | Use |
| --- | --- | --- |
| `xs` | 12px / 16px | Captions, provenance metadata, footnotes |
| `sm` | 14px / 20px | Secondary body text, table cells |
| `base` | 16px / 24px | Body copy |
| `lg` | 18px / 28px | Lead paragraphs, emphasised body |
| `xl` | 24px / 32px | Section headings (Plex Serif) |
| `2xl` | 32px / 40px | Page titles (Plex Serif) |
| `3xl` | 40px / 48px | Landing/hero only |

## Layout concept: the margin rail

Reading columns are deliberately narrow (max ~72ch), like a printed policy page.
Beside the column — right-hand rail on desktop, collapsing to inline chips and
bottom sheets below 768px — sits a persistent **margin rail**: the place provenance
chips, confidence badges, and status flags live, physically separate from the prose
they annotate, the way a lawyer's marginal note sits beside a clause rather than
inside it. This keeps the sentence "the room-rent cap is ₹5,000/day" readable as
plain language while its evidence and confidence sit half a step to the side,
always visible, never a hover-only tooltip.

## Signature element: the provenance chip

The chip that proves a number came from the user's own document is designed like a
**ticket stub** — a small tab with a dashed border simulating a perforation, filled
and solid only in its one fully-verified state; every other state is outlined and
dashed, never a lower-opacity version of verified, so it can never be misread as
confirmed (see "Provenance is three states, not two" above). Clicking it opens the
document viewer to the cited page with the bounding box drawn, as if tearing the stub
to open the ledger to that line. Every other element in the system stays quiet so
this one carries the product's central claim.
