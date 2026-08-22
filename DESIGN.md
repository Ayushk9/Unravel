# Design direction

Status: initial token system for Phase 0 (app shell only). Primitives that put these
tokens to work — `<Money>`, `<ProvenanceChip>`, `<ConfidenceBadge>`, `<VerdictBand>`,
etc. — are built in Phase 1 against a `/kitchen-sink` route, which is also where this
file gets pressure-tested and revised.

## Why this direction

The subject is money, documents, deadlines, and evidence, not health or finance in the
abstract. The visual language comes from **the policy document itself** — page edges,
clause numbering, tabular ledgers, stamps, ticket-stub perforations — not from fintech
gradients, medical iconography, or a generic "AI product" look.

Explicitly avoided: cream `#F4F1EA` + high-contrast serif + terracotta; near-black +
single acid accent; broadsheet hairline-rule layouts; shadcn's out-of-the-box
slate-and-blue.

## Tokens

Six named hex values. Semantic states (verified/unverified, eligibility bands, flag
severities, deadline urgencies) are built as combinations of these plus icon/weight/
border cues — never colour alone.

| Token | Hex | Role |
| --- | --- | --- |
| `--paper` | `#ECEFE9` | Page background — a pale ledger grey-green, not cream |
| `--ink` | `#1C2420` | Primary text — deep charcoal-green, not pure black |
| `--ink-muted` | `#5B685F` | Secondary text, captions, muted labels |
| `--rule` | `#C7CFC2` | Hairline borders, table rules, dividers |
| `--stamp` | `#1F5E4A` | Primary accent — verified, confirmed, positive action. Reads as ink-stamp green |
| `--flag` | `#AE3A2C` | Danger/flag accent — errors, denied states, at-risk. Reads as a rejection-stamp red-oxide |

Semantic layers (eligibility bands, flag severities, deadline urgency, confidence)
are built in Phase 1 as tints/shades of `--stamp` and `--flag` plus a neutral amber
(`#8A6A1F`-family, to be finalised against real content) for the "at risk / soon /
medium" middle states — never a bare hue swap, always paired with an icon and label.

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
**ticket stub** — a small tab with a dashed perforation on the edge that faces the
document viewer, `--stamp`-coloured when verified, muted/outlined with a dashed
border when unverified (never just a lower-opacity version of the verified state —
unverified gets its own outline treatment, a "?" glyph, and the word "Unverified",
so it can never be misread as confirmed). Clicking it animates the document viewer
open to the cited page with the bounding box drawn, as if tearing the stub to open
the ledger to that line. Every other element in the system stays quiet so this one
carries the product's central claim.
