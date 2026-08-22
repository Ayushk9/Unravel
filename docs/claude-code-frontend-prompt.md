# Claude Code Build Prompt — Frontend Shell & Integration Harness

> Paste everything below the line into Claude Code from the repo root.

---

You are building the **entire frontend** of a health-insurance policy-and-claim assistant for Indian policyholders. This is a capstone project. The backend does not exist yet — it will be built afterwards in parallel vertical slices by three developers. Your frontend is therefore not just a UI: it is the **integration harness** the backend will be built against. Every screen must run today against mock data, and must switch to the real API later by changing one environment variable and nothing else.

Work in phases (Section 10). Stop at the end of each phase, summarise what you built, and wait for my go-ahead before starting the next phase.

---

## 1. Product context

Indian health-insurance policyholders cannot read their own policies (40+ pages of sub-limits, waiting periods, exclusions, proportionate-deduction clauses), cannot tell whether a claim will be paid before they file it, cannot tell which documents are missing, hold policies from multiple insurers with no single view, and almost never escalate a wrong denial to the free and binding Insurance Ombudsman.

The product removes those information barriers. Nine features, built on four shared engines:

| Engine | Responsibility | Features it serves |
| --- | --- | --- |
| A — Document understanding | PDF/image → structured data **with provenance** (page + bounding box) | 1, 3, 5, 8 |
| B — Rules & eligibility | Deterministic reasoning over coverage profile + case timeline | 2, 4, 8 |
| C — Grounded generation | Hybrid retrieval + citation-verified LLM output | 1, 7 |
| D — Data & analytics | Multi-insurer schema, claim state machine, regulator-data ETL | 5, 6, 9 |

The nine features:

1. Plain-language policy analysis (grounded Q&A over the user's own policy, always citing the governing clause)
2. Claim-approval assessment before filing (**rules-based eligibility, not an ML probability**)
3. Hospital-bill line-item extraction and validation (non-payables, duplicates, arithmetic, sub-limit breaches)
4. Missing-document detection before submission
5. Unified multi-insurer policy dashboard
6. End-to-end claim timeline tracking (event log + state machine + derived deadlines)
7. Tailored AI grievance letters with enforced citations
8. Preventive policy-gap alerts (coverage-shape rules + time-based clocks)
9. Insurer benchmarking on published IRDAI / Council for Insurance Ombudsmen data

---

## 2. Non-negotiable rules

These are product-integrity rules, not style preferences. Violating any of them makes the UI dishonest, which is the one failure mode this project cannot afford.

1. **No fact without provenance.** Any value that was extracted from a user's document renders with a provenance affordance (page number + click-to-open-and-highlight). If a mock record has no provenance, render the "unverified" treatment — never render it as if it were confirmed.
2. **No verdict without reasoning.** Eligibility results always show the checks that produced them. There is no bare percentage anywhere in this UI.
3. **Abstention is a first-class state, not an error.** When the system lacks a required fact, the screen says which fact is missing and which document would resolve it. Style it as information, not as a failure.
4. **No claim without a citation** in generated grievance letters. Unsupported sentences render visibly flagged, never silently.
5. **Never imply a guaranteed outcome or give legal advice.** Copy says "assessment", "estimate", "based on your documents". A persistent, non-dismissible-per-session disclaimer appears on every assessment and generated-letter surface.
6. **No live-API illusions.** Do not build anything that assumes an insurer API exists. Policies enter the system only by document upload.
7. **TypeScript strict mode, zero `any`, zero type errors in the final build.**

---

## 3. Stack — use exactly this

| Concern | Choice | Notes |
| --- | --- | --- |
| Build | Vite + React 18 + TypeScript (strict) | |
| Routing | React Router v6 (data routers) | |
| Server state | TanStack Query v5 | All API reads/writes go through it |
| Styling | Tailwind CSS + CSS custom properties for tokens | |
| Components | shadcn/ui (Radix primitives) | Restyle to the tokens in Section 7; do not ship default look |
| Icons | lucide-react | |
| Charts | Recharts | Feature 9 only |
| Forms | react-hook-form + zod | zod schemas mirror API contracts |
| Mocking | **MSW (Mock Service Worker)** | Network-level interception — this is the swap seam |
| PDF viewing | pdf.js via react-pdf | Needed for bounding-box highlight |
| Dates | date-fns | |
| Tests | Vitest + React Testing Library | Component-level only this pass |

Do not add state-management libraries beyond React context plus TanStack Query. Do not add a component library other than shadcn/ui.

---

## 4. The integration seam (most important architectural requirement)

```
src/api/
  client.ts        # thin typed fetch wrapper — the ONLY place fetch() is called
  endpoints/       # one module per resource: policies.ts, claims.ts, documents.ts, ...
  types.ts         # domain types (Section 5) — mirrors backend Pydantic contracts
  queryKeys.ts     # centralised TanStack Query key factory
mocks/
  handlers/        # MSW handlers, one file per resource, mirroring endpoints/
  fixtures/        # deterministic seed data (Section 8)
  browser.ts       # MSW worker setup
  devtools.tsx     # scenario switcher (Section 8.3)
```

Rules:

- Components never call `fetch` and never import from `mocks/`. They call hooks in `src/api/endpoints/*`, which call `client.ts`.
- `VITE_API_MODE=mock` starts MSW. `VITE_API_MODE=live` does not, and `client.ts` points at `VITE_API_BASE_URL`. **Nothing else in the codebase reads these variables.**
- Every MSW handler's URL path, method, request body shape, and response body shape is the proposed backend contract. Treat it as a specification you are authoring, not as throwaway mock code.
- Produce `CONTRACTS.md` at the repo root: a table of every endpoint (method, path, request shape, response shape, error codes, whether it is idempotent, whether it is long-running). This is the document the backend team will review before writing FastAPI routes, so write it for a reader, not as a code dump.
- Long-running operations (document parsing, letter generation) must be modelled as **job endpoints**: `POST` returns `{ job_id, status: "queued" }`, and the client polls `GET /jobs/{job_id}`. Do not model them as slow synchronous calls — the real backend will not be synchronous, and this is where a wrong contract costs the most rework later.

---

## 5. Domain types

Author these in `src/api/types.ts`. Conventions: money is **integer paise** (never floats), dates are ISO-8601 strings, IDs are UUID strings. Field names are `snake_case` to match the backend exactly — do not camelCase them at the boundary.

```ts
type UUID = string;
type ISODate = string;      // "2026-03-01"
type ISODateTime = string;  // "2026-03-01T09:15:00+05:30"
type Paise = number;        // ₹5,000 => 500000

type Confidence = "high" | "medium" | "low";

interface Provenance {
  document_id: UUID;
  page: number;                       // 1-indexed
  bbox: [number, number, number, number] | null; // x0,y0,x1,y1 normalised 0..1
  snippet: string | null;
}

interface Extracted<T> {          // wrapper for every extracted field
  value: T | null;
  confidence: Confidence;
  provenance: Provenance | null;
  user_confirmed: boolean;
}

// --- Engine A / D: policy ---
interface Insurer { id: UUID; name: string; irdai_code: string | null; }

interface SubLimit {
  category: "room_rent" | "icu" | "procedure" | "ambulance" | "opd" | "other";
  label: string;
  cap_amount: Extracted<Paise>;
  cap_basis: "per_day" | "per_claim" | "per_policy_year" | "percent_of_sum_insured";
  percent_value: number | null;
}

interface WaitingPeriod {
  kind: "initial" | "disease_specific" | "pre_existing" | "maternity";
  months: Extracted<number>;
  applies_to: string | null;        // e.g. "cataract"
  starts_on: ISODate | null;
  expires_on: ISODate | null;       // derived server-side
}

interface CoverageProfile {
  policy_id: UUID;
  sum_insured: Extracted<Paise>;
  co_pay_percent: Extracted<number>;
  sub_limits: SubLimit[];
  waiting_periods: WaitingPeriod[];
  exclusions: Extracted<string>[];
  intimation_deadline_hours: Extracted<number>;
  extraction_completeness: number;   // 0..1, drives the "review these fields" banner
}

interface Policy {
  id: UUID;
  insurer: Insurer;
  policy_number: string;
  product_name: string;
  policy_type: "individual" | "family_floater" | "group_employer" | "top_up";
  start_date: ISODate;
  end_date: ISODate;
  members: Member[];
  coverage_profile: CoverageProfile | null;   // null while parsing
  source_document_id: UUID;
}

interface Member { id: UUID; full_name: string; relationship: string; date_of_birth: ISODate | null; }

// --- Engine A: documents ---
type DocumentType =
  | "policy_schedule" | "policy_wording" | "discharge_summary" | "itemised_bill"
  | "payment_receipt" | "investigation_report" | "denial_letter" | "id_proof" | "unknown";

interface StoredDocument {
  id: UUID;
  file_name: string;
  mime_type: string;
  page_count: number;
  uploaded_at: ISODateTime;
  detected_type: Extracted<DocumentType>;
  parse_status: "queued" | "parsing" | "parsed" | "failed";
  parse_error: string | null;
}

// --- Engine B: eligibility ---
type CheckStatus = "satisfied" | "at_risk" | "failed" | "unknown";

interface EligibilityCheck {
  id: string;                       // stable rule id, e.g. "ped_waiting_period"
  title: string;                    // "Pre-existing disease waiting period"
  status: CheckStatus;
  explanation: string;              // plain language, includes date arithmetic
  governing_clause: Provenance | null;
  missing_fact: string | null;      // set when status === "unknown"
  resolving_document: DocumentType | null;
}

interface EligibilityAssessment {
  claim_id: UUID;
  band: "likely_eligible" | "at_risk" | "likely_ineligible" | "insufficient_information";
  checks: EligibilityCheck[];
  ombudsman_precedent: OmbudsmanAward[];   // similar fact patterns, may be empty
  generated_at: ISODateTime;
}

// --- Engine B: bill validation ---
interface BillLineItem {
  id: UUID; description: string; quantity: number;
  rate: Paise; amount: Paise; provenance: Provenance | null;
}

interface ValidationFlag {
  severity: "info" | "warning" | "error";
  rule: "non_payable_item" | "duplicate_line" | "arithmetic_mismatch" | "sub_limit_breach";
  message: string;
  line_item_ids: UUID[];
  estimated_impact: Paise | null;
}

// --- Engine B: document completeness ---
interface CompletenessReport {
  claim_id: UUID;
  required: DocumentType[];
  present: DocumentType[];
  missing: DocumentType[];
  advisory_note: string;
}

// --- Engine D: claim lifecycle ---
type ClaimState =
  | "intimated" | "documents_submitted" | "under_review" | "queried"
  | "approved" | "denied" | "escalated" | "resolved";

interface ClaimEvent {
  id: UUID; claim_id: UUID;
  from_state: ClaimState | null; to_state: ClaimState;
  occurred_at: ISODateTime; note: string | null;
  source: "user" | "insurer_letter" | "system";
}

interface Deadline {
  id: string; label: string;         // "Ombudsman filing window"
  due_at: ISODateTime; days_remaining: number;
  basis: string;                     // which rule + which event derived it
  urgency: "normal" | "soon" | "critical" | "expired";
}

interface Claim {
  id: UUID; policy_id: UUID; member_id: UUID;
  claim_type: "cashless" | "reimbursement";
  admission_type: "planned" | "emergency";
  hospital_name: string;
  admitted_on: ISODate | null; discharged_on: ISODate | null;
  claimed_amount: Paise | null; settled_amount: Paise | null;
  current_state: ClaimState;         // projection over the event log
  events: ClaimEvent[];
  deadlines: Deadline[];
}

// --- Engine C: grounded generation ---
interface Citation {
  id: string; kind: "policy_clause" | "regulation" | "ombudsman_award";
  label: string; provenance: Provenance | null; external_url: string | null;
}

interface GrievanceDraft {
  id: UUID; claim_id: UUID;
  rung: "insurer_grievance_cell" | "irdai_bima_bharosa" | "insurance_ombudsman";
  subject: string;
  paragraphs: { text: string; citation_ids: string[]; verified: boolean }[];
  citations: Citation[];
  evidence_checklist: { item: string; satisfied: boolean }[];
  citation_precision: number;        // 0..1, shown in the QA strip
}

interface OmbudsmanAward {
  id: UUID; case_reference: string; insurer_name: string;
  decided_on: ISODate; denial_ground: string;
  outcome: "upheld" | "overturned" | "partially_allowed";
  summary: string; external_url: string | null;
}

// --- Engine B: alerts ---
interface Alert {
  id: UUID; policy_id: UUID;
  kind: "room_rent_below_market" | "waiting_period_expiring" | "renewal_due"
      | "no_maternity_cover" | "low_sum_insured";
  severity: "info" | "warning" | "critical";
  title: string; explanation: string;
  suggested_action: string | null;
  reference_source: string | null;   // for estimate-based alerts
  triggers_on: ISODate | null;
}

// --- Engine D: benchmarking ---
interface InsurerBenchmark {
  insurer: Insurer;
  period: string;                    // "FY2024-25"
  claim_settlement_ratio: number | null;
  incurred_claims_ratio: number | null;
  avg_turnaround_days: number | null;      // often null — render "Not reported"
  complaints_per_10k_policies: number | null;
  ombudsman_cases_lost_share: number | null;
  source: { name: string; published_on: ISODate; url: string };
}
```

Every nullable field above is nullable because the real data genuinely is. Build UI for the null case in each one.

---

## 6. Routes and screens

| Route | Screen | Features | Notes |
| --- | --- | --- | --- |
| `/` | Landing + sign-in stub | — | Local stubbed session, no real auth |
| `/dashboard` | Household overview | 5, 8 | Policy cards, active claims, top alerts |
| `/policies` | Policy list | 5 | Side-by-side comparison mode |
| `/policies/upload` | Upload + parse | 1 | Job polling, low-confidence review |
| `/policies/:id` | Policy detail | 1 | Coverage profile with provenance |
| `/policies/:id/ask` | Grounded Q&A | 1 | Split view: answer + cited clause |
| `/claims` | Claim list | 6 | Grouped by state, deadlines surfaced |
| `/claims/new` | Claim wizard | 4, 2, 3 | Multi-step |
| `/claims/:id` | Claim workspace | 6, 2, 3, 4 | Tabbed: Timeline / Eligibility / Documents / Bill |
| `/claims/:id/grievance` | Grievance drafting | 7 | Editor + evidence panel |
| `/alerts` | Alerts inbox | 8 | Grouped by severity |
| `/insurers` | Benchmarking | 9 | Charts + comparison table |
| `/settings` | Profile, members, data | — | Includes "delete my documents" |

### 6.1 Screen specifications

**`/policies/upload` — upload and parse (Feature 1)**

Three visible stages, driven by real job polling: *Uploading* → *Parsing* (indeterminate, with the file name and page count) → *Review extracted terms*. The review stage is the point of the screen: render every extracted field grouped by category, with `confidence: "low"` fields hoisted into a "Confirm these 4 values" block at the top. Each low-confidence field shows the extracted value, the page snippet it came from, and inline Confirm / Correct controls. Confirming sets `user_confirmed: true`. A policy can be saved with unconfirmed fields, but those fields carry the unverified treatment everywhere downstream.

*Scenario to build against:* the user uploads a 46-page scanned policy. Sum insured extracts at high confidence; the room-rent cap sits in a nested sub-limits table and extracts at low confidence as `₹5,000/day`. The screen must make the room-rent field impossible to miss, because that single number determines whether a proportionate deduction later wipes out 60% of their claim.

**`/policies/:id` — policy detail (Feature 1)**

Two-pane on desktop, stacked on mobile. Left: the coverage profile — sum insured, co-pay, sub-limits table, waiting-period timeline (a horizontal track showing months served vs remaining, with the expiry date), exclusions list. Right: the document viewer. Clicking any provenance chip scrolls the viewer to the page and draws the bounding-box highlight. On mobile the viewer opens as a sheet.

**`/policies/:id/ask` — grounded Q&A (Feature 1)**

A question input with suggested questions ("Is my knee surgery covered?", "What happens if I choose a ₹12,000/day room?"). The answer renders as plain-language prose with inline superscript citation markers; each marker opens the clause in the viewer. If retrieval returns nothing usable, render the abstention card: "Your policy documents don't answer this. The clause may be in a document you haven't uploaded." Never render a confident answer without markers.

**`/claims/new` — claim wizard (Features 4, 2, 3)**

Steps: 1) Which policy and member. 2) Claim type and admission type. 3) Upload documents — each upload shows its auto-detected type with an editable dropdown, and a live completeness panel updates as files land. 4) Bill validation results, if an itemised bill was uploaded. 5) Eligibility assessment. 6) Summary and file. Steps 4 and 5 are read-only outputs. The wizard must be resumable — persist step state so a refresh does not lose it.

**`/claims/:id` — Eligibility tab (Feature 2)**

Top: the verdict band, rendered as a labelled band with an explanatory sentence — never a percentage, never a gauge or speedometer. Below: the checks list, ordered failed → at_risk → unknown → satisfied. Each check is expandable and shows the plain-language explanation with the date arithmetic spelled out ("Your policy started 14 Mar 2024. The pre-existing-disease waiting period is 48 months, so it runs to 14 Mar 2028. Your admission on 2 Apr 2026 falls 23 months inside it.") plus a link to the governing clause. `unknown` checks show the missing fact and a button to upload the resolving document. If the band is `insufficient_information`, the checks list is secondary to a prominent card naming exactly what is missing.

Below the checks, the precedent panel: matching Ombudsman awards with their fact pattern and outcome, framed as "cases with a similar denial ground", never as a prediction about this claim.

**`/claims/:id` — Bill tab (Feature 3)**

The extracted line items as a table with the flagged rows visually marked; a flags panel beside it summarising each flag with its estimated rupee impact and a total "amount at risk". Clicking a flag highlights its rows; clicking a row opens the bill page in the viewer.

*Scenario to build against:* the bill contains "Surgical gloves — ₹4,200" (non-payable consumable), a duplicated "OT charges" row, and a room rent of ₹12,000/day against a ₹5,000/day cap. All three flags render with distinct rules and a combined impact figure.

Do **not** build any market-rate or "overpriced" comparison. Reliable reference pricing does not exist for this market.

**`/claims/:id` — Timeline tab (Feature 6)**

A vertical event timeline rendered directly from the append-only event log, newest first, each entry showing state transition, timestamp, source, and note. Above it, active deadlines as countdown cards, each stating the rule that derived it ("30 days since the insurer's last response — you may now escalate"). Urgency drives treatment; `expired` deadlines stay visible with an expired treatment rather than disappearing. Adding an event is a modal, not an inline edit — the log is append-only and the UI should feel that way.

**`/claims/:id/grievance` — grievance drafting (Feature 7)**

Three regions: rung selector at top (with a one-line explanation of what each rung is and its filing window), the letter body in the centre, the evidence panel on the right. Every paragraph shows its citation chips beneath it. Paragraphs with `verified: false` render with a warning treatment and a "This sentence isn't supported by your documents" note — the user can keep it, edit it, or delete it, but they must see it. A QA strip shows the citation-precision figure. Actions: copy, download as .docx, download the evidence checklist.

**`/insurers` — benchmarking (Feature 9)**

A sortable comparison table plus two or three charts. Every metric cell carries a source stamp (source name + publication date) and renders **"Not reported"** rather than 0 or a blank when the value is null — patchy turnaround data is the norm and hiding it would misrepresent the regulator's data. A visible note separates regulator data from (future) user-reported data; do not build the user-reported section this pass, but leave the labelled placeholder so the separation is architecturally visible.

---

## 7. Design direction

Before writing any component, write `DESIGN.md`: a token system with 5–6 named hex values, two typefaces with defined roles and a type scale, a layout concept, and one signature element. Then review it against this brief and revise anything that reads as a generic default.

Constraints on that exploration:

- **Not** the AI-default looks: cream `#F4F1EA` + high-contrast serif + terracotta accent; near-black + single acid accent; broadsheet hairline-rules layout. Also not the shadcn out-of-the-box slate-and-blue.
- The subject is money, documents, deadlines, and evidence. The visual world to draw from is the **document itself** — page edges, clause numbering, marginalia, stamps, redaction, tabular ledgers — not fintech gradients and not medical iconography.
- Semantic colour must be doing real work. You need distinguishable, accessible treatments for: verified vs unverified extraction; the four eligibility bands; the four flag severities; the four deadline urgencies. Design these as one coherent system, not four ad-hoc palettes. Do not rely on hue alone — every state needs a second cue (icon, weight, border, label) because a large share of the audience will read this on a cheap phone in bright light.
- Indian number formatting throughout: `Intl.NumberFormat('en-IN')`, so `₹5,00,000`, plus lakh/crore shorthand where space is tight. A `<Money>` component is the only place rupee formatting exists.
- Copy is in plain Indian English, sentence case, active voice. Say "Room rent above your cap" not "Sub-limit violation detected". Errors state what happened and the next action. Empty states invite an action.
- Quality floor, unannounced: responsive to 360px, visible keyboard focus, `prefers-reduced-motion` respected, semantic landmarks, form labels bound, tables with proper headers.

The signature element should be the **provenance affordance** — the thing that makes this product different is that every number can be traced back to the line in the PDF it came from. Spend your design boldness there and keep everything around it quiet.

---

## 8. Mock data and scenario control

### 8.1 Fixtures

Deterministic and hand-authored (no faker randomness at runtime). Build one household:

- **Policies:** an employer group floater (₹5 lakh, maternity excluded, 30-day initial waiting period) and a retail individual policy (₹10 lakh, ₹5,000/day room-rent cap, 48-month PED waiting period, maternity covered after 24 months). Extraction completeness `0.82` on the retail policy, with the room-rent cap at `confidence: "low"`.
- **Members:** four — self, spouse, one child, one dependent parent.
- **Claims:** (a) a denied reimbursement claim, denial ground "pre-existing disease", with a full event log ending in `denied` and an active Ombudsman filing deadline; (b) a claim in `under_review` with one missing document; (c) a settled claim for the dashboard's history.
- **Bill:** an itemised bill with ~18 line items containing the three planted defects from Section 6.1.
- **Ombudsman awards:** six awards, three with a PED fact pattern (two overturned, one upheld).
- **Benchmarks:** ten insurers, with at least three having `avg_turnaround_days: null`.
- **Alerts:** four, one of each kind, including a waiting period expiring in 11 days.

Fixture values must be internally consistent — the room-rent cap in the policy is the same number the bill flag compares against, and the dates in the event log actually produce the deadlines shown. Inconsistent fixtures will hide real bugs.

### 8.2 Realistic transport behaviour

Handlers simulate latency (parse job 4–8s across polls, retrieval 800ms, plain reads 150–400ms) so loading states are exercised rather than theoretical.

### 8.3 Dev toolbar

A floating panel, dev-build only, that forces states without editing code: loading / empty / error / slow network / low-confidence extraction / abstention / each eligibility band / expired deadline. Every screen must be reachable in every state it can occupy through this panel. This is how the team demos edge cases to the mentor, so treat it as a real feature.

---

## 9. State coverage requirement

Each screen implements, and I will check for, five states:

1. **Loading** — skeletons matching the final layout, not spinners.
2. **Empty** — an invitation to act, with the action available in place.
3. **Error** — what failed, and a retry that actually retries.
4. **Degraded** — data present but low-confidence or incomplete, with the unverified treatment and a path to confirm.
5. **Abstained** — the system declining to answer, with the missing fact named.

---

## 10. Phases

Stop and report after each. Do not run ahead.

| Phase | Deliverable | Done when |
| --- | --- | --- |
| 0 | Scaffold: Vite + TS strict, Tailwind, shadcn, router, TanStack Query, MSW wired, `DESIGN.md`, `DECISIONS.md` | `npm run dev` serves an app shell; MSW intercepts a health-check call |
| 1 | Design system + primitives: tokens, `<Money>`, `<ProvenanceChip>`, `<DocumentViewer>`, `<ConfidenceBadge>`, `<VerdictBand>`, `<DeadlineCard>`, `<CitationList>`, empty/error/skeleton primitives, app layout and navigation | Every primitive rendered in a `/kitchen-sink` dev route in all its states |
| 2 | Contracts + fixtures + all MSW handlers + `CONTRACTS.md` + dev toolbar | Every endpoint the app will need returns realistic data; `CONTRACTS.md` is reviewable by the backend team |
| 3 | Features 5 and 1 — dashboard, policy list, upload/parse/review, policy detail, grounded Q&A | Provenance click-through works end to end |
| 4 | Features 6, 4, 2 — claim list, claim wizard, timeline, eligibility | All four eligibility bands reachable via the toolbar |
| 5 | Features 3 and 7 — bill validation, grievance drafting | Unverified paragraphs render flagged |
| 6 | Features 8 and 9 — alerts, benchmarking | "Not reported" renders correctly |
| 7 | Polish: accessibility pass, responsive pass at 360/768/1280, component tests for the primitives, README | `npm run build` and `tsc --noEmit` both clean |

---

## 11. Working agreement

- Branch per phase off `main`, small commits, conventional commit messages. Do not force-push.
- When a decision is ambiguous, **pick the more conservative option, proceed, and log it** in `DECISIONS.md` as: what was ambiguous, what you chose, what would change if we chose otherwise. Do not block on questions unless the ambiguity affects the API contract — those, raise immediately, because three people will build against them.
- Do not invent regulatory facts, statutory deadlines, monetary ceilings, or IRDAI figures. Where fixture data needs a regulatory number, use an obvious placeholder and list it in `DECISIONS.md` under "Needs verification against primary source".
- Do not scaffold backend code, database migrations, or Docker files this pass.

## 12. Out of scope

Real authentication, real OCR or LLM calls, payments, notifications, email/SMS parsing, PWA/offline, localisation beyond keeping copy in one module for later extraction, and any insurer API integration.
