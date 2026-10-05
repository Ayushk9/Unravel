# API contracts

Written for the backend team to review before writing FastAPI routes. Every endpoint
below is implemented as an MSW handler in `apps/web/mocks/handlers/`, backed by the
fixtures in `apps/web/mocks/fixtures/`, and typed end-to-end through
`packages/contracts-ts/src/types.ts` + `schemas.ts`. Treat the handlers as the
executable spec — if this document and a handler ever disagree, the handler is
probably right and this document is stale; file that as a bug.

This is Phase 2 of the frontend build. It implements every ruling in
`docs/API_DECISIONS.md` exactly as written; where this document interprets something
`API_DECISIONS.md` left open, that's called out explicitly in §4.

---

## 1. Conventions (all ratified, see docs/API_DECISIONS.md)

- **Base path:** every route below is relative to `/api/v1` (D-01).
- **Casing:** `snake_case` on the wire, both directions, no transform (D-02).
- **Collections** return `{ items, next_cursor, total }`. **Single resources** return
  the object bare. **Errors**, on every non-2xx response including validation
  failures, return:
  ```json
  { "error": { "code", "message", "field_errors", "request_id", "retryable" } }
  ```
  (D-03)
- **Nulls are always emitted, never omitted** — every field is present in every
  response (D-05).
- **Every enum has an escape-hatch member** (`"unknown"` or `"other"`, chosen per
  enum — see the comment block at the top of `types.ts`), and the frontend parses
  through a zod `.catch(...)` at that value (D-06).
- **Auth:** `Authorization: Bearer <token>` is asserted on every handler. There is no
  `household_id` parameter anywhere — ownership comes from the token, and a resource
  belonging to another household is a `404`, never a `403` (D-09, D-10).
- **Jobs:** exactly three endpoints are long-running jobs (`POST` returns `202` +
  `{ job_id, kind, status: "queued" }`, polled via `GET /jobs/{job_id}`). Every other
  endpoint is synchronous. See §2.
- **Idempotency:** `Idempotency-Key` is required on exactly two endpoints and replayed
  verbatim on a repeat key (D-13). Missing the header on those two is a `422` in this
  implementation (see §4 — the status code for a missing required header isn't
  specified in `API_DECISIONS.md`).
- **Field correction** is a targeted `PATCH` to a dotted field path, never a
  whole-profile `PUT` (D-15).
- **Claim state** is a projection over an append-only event log. Clients never set
  `current_state` directly (D-16).
- **Deadlines** (`due_at`, `days_remaining`, `basis`, `urgency`) are always computed
  server-side, from the event log, at request time — never stored statically (D-17).
- **Frontend transport modes (`VITE_API_MODE`)** — not a backend concern, documented
  here so the backend team knows what to expect from the frontend during the
  transition: `mock` (MSW only), `live` (real backend only, MSW never starts), and
  `hybrid` (per-request — a fixed allowlist of routes go live against
  `VITE_API_BASE_URL`, everything else stays on MSW). The allowlist lives in
  `apps/web/src/api/hybridRoutes.ts` (`HYBRID_LIVE_ROUTES`) and is currently:
  `POST /documents`, `GET /jobs/{id}`, `GET /policies/{id}`. Hybrid mode exists so
  individual endpoints can be cut over to the real backend one at a time as slices
  land, without the whole app losing its mock fallback. See
  `apps/web/mocks/hybridPassthrough.ts` for how MSW is kept from shadowing an
  allowlisted route (its handlers are origin-agnostic `*/api/v1/...` patterns, which
  would otherwise still match a request aimed at a real host).

---

## 2. Endpoints

| # | Method & path | Request | Response | Notable errors | Sync / Job | Paginated | Idempotency-Key |
|---|---|---|---|---|---|---|---|
| 1 | `GET /health` | — | `{ status: "ok" }` | — (public, D-24) | Sync | — | — |
| 2 | `POST /documents` | multipart: `file`, `claim_id` | 202 `JobAccepted` (kind `parse_document`) | 401, 413 (>25MB), 422 (bad type / missing file) | **Job**, 4–8s | — | **Required** |
| 3 | `GET /documents` | `?cursor&limit&claim_id` | `Collection<StoredDocument>` | 401 | Sync | Cursor | — |
| 4 | `GET /documents/{id}` | — | `StoredDocument` | 401, 404 | Sync | — | — |
| 5 | `PATCH /documents/{id}` | `{ detected_type }` | `StoredDocument` | 401, 404, 422 | Sync | — | — |
| 6 | `DELETE /documents/{id}` | — | 204 | 401, 404 | Sync (soft delete, D-20) | — | — |
| 7 | `GET /policies` | — | `Policy[]` | 401 | Sync | No (full array) | — |
| 8 | `POST /policies` | `{ source_document_id }` | `Policy` | 401, 409, 422 | Sync | — | — |
| 9 | `GET /policies/{id}` | — | `Policy` (embeds `coverage_profile`) | 401, 404 | Sync | — | — |
| 10 | `PATCH /policies/{id}/coverage-profile/fields/{field_path}` | `{ value, user_confirmed }` | `Policy` | 401, 404, 409, 422 | Sync | — | — |
| 11 | `POST /policies/{id}/questions` | `{ question }` | 202 `JobAccepted` (kind `answer_question`) | 401, 404 | **Job**, 3–6s | — | — |
| 12 | `GET /members` | — | `Member[]` | 401 | Sync | No (full array) | — |
| 13 | `GET /claims` | — | `Claim[]` | 401 | Sync | No — see §4 gap | — |
| 14 | `POST /claims` | `ClaimCreateRequest` | 201 `Claim` | 401, 422 | Sync | — | — |
| 15 | `GET /claims/{id}` | — | `Claim` | 401, 404 | Sync | — | — |
| 16 | `POST /claims/{id}/events` | `{ to_state, occurred_at, note }` | `Claim` (recomputed) | 401, 404, **409** (illegal transition — allowed targets in `field_errors`, see §3) | Sync | — | — |
| 17 | `POST /claims/{id}/eligibility` | — | `EligibilityAssessment` | 401, 404 | Sync | — | — |
| 18 | `POST /claims/{id}/completeness` | — | `CompletenessReport` | 401, 404 | Sync | — | — |
| 19 | `POST /claims/{id}/bill-validation` | — | `BillValidationReport` | 401, 404, **409** (bill not parsed yet) | Sync | — | — |
| 20 | `POST /claims/{id}/grievance-drafts` | `{ rung }` | 202 `JobAccepted` (kind `generate_grievance_draft`) | 401, 404 | **Job**, 20–30s | — | **Required** |
| 21 | `GET /alerts` | — | `Alert[]` | 401 | Sync | No (full array) | — |
| 22 | `GET /ombudsman-awards` | `?cursor&limit` | `Collection<OmbudsmanAward>` | 401 | Sync | Cursor | — |
| 23 | `GET /insurers/benchmarks` | — | `InsurerBenchmark[]` | 401 | Sync | No (full array) | — |
| 24 | `GET /jobs/{job_id}` | — | `Job<TResult>` | 401, 404 | Sync (this is what gets polled) | — | — |

24 endpoints. `#1` (`health`) is infra, not part of a vertical slice. `#3`'s
`claim_id` filter and all of `#5` are Phase 4 additions, not in the ratified
`API_DECISIONS.md` endpoint list — see §4.

---

## 3. Non-obvious behaviour worth reading before you build

**`field_path` is addressed by category/kind label, not array index.** D-15's own
examples (`sub_limits.room_rent.cap_amount`, `waiting_periods.pre_existing.months`)
address `SubLimit` by `category` and `WaitingPeriod` by `kind` — not by position in
the array. `apps/web/mocks/db.ts`'s `patchCoverageField` implements exactly that
lookup. Only three field paths are addressable in this mock: `sum_insured`,
`co_pay_percent`, `intimation_deadline_hours` (top-level), plus the two dotted forms
above — extend the `if` chain there as more fields need correcting.

**Illegal claim transitions put the allowed targets in `field_errors`, one entry per
allowed state.** There's no dedicated field in the ratified error shape for "list of
allowed values," so this mock represents it as multiple `field_errors` entries, all
with `field: "to_state"` and `message` set to one allowed state name each. The
frontend maps over them to get the allowed-state list. This is a convention, not a
literal reading of D-04 — flagged in §4.

**The claim state machine graph** (`apps/web/mocks/db.ts`, `CLAIM_TRANSITIONS`) is a
mock-only assumption, not a ratified rule:
```
intimated          -> documents_submitted, queried
documents_submitted -> under_review, queried
under_review        -> queried, approved, denied
queried             -> documents_submitted, under_review
approved            -> resolved
denied              -> escalated, resolved
escalated           -> resolved
resolved            -> (terminal)
```
`API_DECISIONS.md` specifies the *mechanism* (append-only log, 409 with allowed
targets) but never the graph itself. See §4.

**Deadlines are computed from the event log at request time, every time**, not read
from storage — `apps/web/mocks/deadlines.ts`. The one currently implemented is the
Ombudsman filing window on a `denied` claim: `due_at = denied_event.occurred_at +
PLACEHOLDER_OMBUDSMAN_FILING_WINDOW_DAYS`. That constant is an obvious placeholder
(`apps/web/mocks/fixtures/reference-data.ts`) — see `DECISIONS.md`.

**Eligibility is computed from the policy's actual `coverage_profile`**, not
hand-written per claim (`apps/web/mocks/eligibility.ts`) — it walks the real
`waiting_periods` array, compares `claim.admitted_on` against each `expires_on` with
plain ISO-date string comparison (not `Date` parsing — see D-12's timezone warning),
and derives `band` from the worst check status present. This is what guarantees the
fixture-integrity requirement that eligibility explanations can't drift from the
waiting-period data they describe.

**Bill validation returns real planted-defect data only for the one fixture claim
that has it** (`ids.claim.denied` — see `apps/web/mocks/fixtures/bill.ts`). Any other
claim with a parsed itemised bill gets a single synthetic line item with no flags,
rather than an error — a real backend would run actual rules here.

**Job polling:** the frontend's polling policy (`apps/web/src/api/endpoints/jobs.ts`)
is every 1s for the first 10s, then every 3s, hard timeout at 180s (D-08). Simulated
job durations in this mock: `parse_document` 4–8s, `answer_question` 3–6s,
`generate_grievance_draft` 20–30s, each picked once per job at creation (not
re-randomised per poll). Job state (and the rest of the mock db) is persisted to
`sessionStorage` and rehydrated on load (`apps/web/mocks/db.ts`) — a page refresh
mid-job recovers the running job's actual elapsed progress instead of restarting it,
matching what a real backend's persistent job store would do.

**Idempotency replay** stores the exact response body and status the first request
produced, keyed by the `Idempotency-Key` header value, and returns it byte-for-byte
on a repeat — no re-processing (`apps/web/mocks/db.ts`, `idempotencyStore`). This
mock doesn't expire the 24h window D-13 specifies; a real backend must.

**Citation markers in generated prose** (Q&A answers, and eventually grievance
paragraphs) use a `[[n]]` token embedded in the text, where `n` is the 1-indexed
position in that response's `citations` array — parsed by `<CitedProse>`
(`apps/web/src/components/primitives/CitedProse.tsx`) into a clickable superscript.
This is a convention this mock invented, not something either ratified doc
specifies — worth a formal line if the backend team needs to match it exactly.

**Phase 4: `PATCH /documents/{id}` corrects a misclassified `detected_type`.**
Not in the ratified endpoint list — added because the claim wizard's Documents
step and the claim workspace's Documents tab both require an editable
type-correction dropdown, and nothing existing addressed it. Body:
`{ detected_type: DocumentType }`. Modelled on D-15's targeted-PATCH pattern:
sets `user_confirmed: true` and bumps `confidence` to `"high"`, preserving the
original `provenance`. See §4.

**Phase 4: `GET /documents?claim_id=...` filters the existing paginated
collection** rather than being a new endpoint — a claim's own documents are a
subset of the same resource, so this is an additive query parameter on
endpoint `#3`, not a contract-shape change. `apps/web/mocks/handlers/documents.ts`
routes it through the existing `documentsForClaim()` lookup before paginating.

**Phase 4: claim-context document classification is filename-keyword-matched**
(`apps/web/mocks/handlers/documents.ts`, `detectClaimDocumentType`), not a fixed
constant like Phase 3's upload flow. A file named e.g. `discharge-summary.pdf`
classifies as `discharge_summary`; anything unmatched defaults to
`itemised_bill`. Mock-only realism so the wizard's "3 of 4 required documents"
scenario is actually reachable by uploading distinctly-named files, and so the
editable-dropdown correction control has a reason to exist beyond the default
case. Not a contract concern — a real classifier reads file content, not names.

**Phase 4: the dev toolbar's "Force illegal transition (409)" is deterministic,
not just "pick something illegal."** `POST /claims/{id}/events` checks this
scenario flag before validating the requested transition at all, and if set,
always 409s with the *current* claim's real allowed-target list in
`field_errors` — regardless of what `to_state` was actually requested. This
exists so the inline allowed-states recovery UI is reachable on demand rather
than requiring the tester to already know the state machine well enough to
pick an illegal move by hand.

---

## 4. Ambiguous or underspecified — needs a decision or a ratified line

These are gaps found while building against `API_DECISIONS.md`, not places this
implementation disagrees with it. Each was resolved with a documented, reversible
assumption so Phase 2 could proceed; none should be read as settled.

1. **Resolved by D-23 (top-left origin).** Original note: `Provenance.bbox` coordinate origin is unspecified. Built in Phase 1 as
   top-left origin (screen/image space). Genuinely contract-affecting — Engine A has
   to emit bbox in whatever convention the frontend assumes, or every highlight
   renders vertically mirrored. Needs a ratified line (see `DESIGN.md` and
   `DECISIONS.md`).

2. **`StoredDocument` had no way to associate a document with a claim.** Added
   `claim_id: UUID | null` to the type in Phase 2 (`packages/contracts-ts/src/types.ts`)
   — without it, Feature 4 (completeness) and the claim workspace's Documents tab
   can't be implemented at all. This is additive and non-breaking, but it's a real
   change to a "frozen in week one" table (`API_DECISIONS.md` §7) and needs sign-off,
   not just frontend-side assumption.

3. **`GET /claims` pagination is unstated.** `API_DECISIONS.md` §5's pagination table
   lists documents/claim-events/ombudsman-awards as paginated and
   policies/members/alerts/benchmarks as full arrays — claims appear in neither list.
   Implemented as a full array, by the same "a household has a bounded number of
   these" reasoning the ratified table uses for policies and alerts. Worth an
   explicit ruling since three developers will build against whichever way this goes.

4. **`POST /policies`'s real trigger is unclear.** `API_DECISIONS.md` §7 lists it
   under Slice 1, but D-07's job design has the parse job itself create the `Policy`
   record (that's what makes `PATCH .../fields/{path}` correctable before any
   separate "save" step could happen — `PATCH` targets an id that must already
   exist). This mock implements `POST /policies` as an idempotent "ensure a policy
   exists for this already-parsed document" call that a real upload flow may never
   actually need to invoke. Flagged, not resolved.

5. **The 409 "allowed transition targets" shape is inferred, not specified.**
   D-04's note says a bad claim transition's `field_errors` "lists the allowed target
   states," but not the shape. This mock uses one `field_errors` entry per allowed
   state (`{ field: "to_state", message: "<state>" }`) — see §3. A single entry with
   a comma-joined message would also satisfy a literal reading; worth ratifying one
   way so the frontend's parsing code doesn't guess.

6. **The claim state machine's transition graph isn't specified anywhere** — only
   the mechanism (append-only log, 409 on illegal transitions) is ratified. The graph
   in §3 is this mock's invention. Needs review by whoever owns Slice 2 before real
   claims start flowing through it.

7. **Missing-required-header status code.** D-13 says `Idempotency-Key` is
   "required" on two endpoints but doesn't say what happens if it's absent. D-04's
   status table has no generic `400`; this mock uses `422` (validation failure) with
   a `field_errors` entry naming the header. Reasonable, not specified.

8. **Every regulatory number is a flagged placeholder**, per `API_DECISIONS.md` §8's
   own rule — see `apps/web/mocks/fixtures/reference-data.ts` and the "Needs
   verification against primary source" list in `DECISIONS.md`. Not a new gap, just
   flagging that it's load-bearing here: the Ombudsman filing deadline shown on the
   denied claim fixture is computed from a placeholder, not a real figure.

9. **Citation-marker convention in generated prose is unratified** (added in Phase
   3). Q&A answers embed `[[n]]` tokens in the text so the frontend can render
   clickable superscripts; nothing in `API_DECISIONS.md` specifies this, and
   Feature 7 (grievance drafting, Phase 5) will need the same mechanism. See §3.

10. **`PATCH /documents/{id}` for type correction is a new endpoint, not a ratified
    one** (added in Phase 4 — endpoint `#5`, §3). The claim wizard and the claim
    workspace's Documents tab both need to let the user correct a misclassified
    document type, and nothing in `API_DECISIONS.md`'s slice-1 endpoint list covers
    it. Modelled deliberately on D-15's targeted-PATCH shape rather than inventing
    something new. Needs sign-off the same way item 2 above does.

11. **`GET /documents?claim_id=...` is an additive filter on an existing paginated
    endpoint, not a new one** (added in Phase 4, §3) — lower-risk than item 10
    since it doesn't change the response shape, but still worth a ratified line so
    Slice 1's implementer knows the frontend expects it.

12. **The claim wizard's resumability doesn't cover steps 1–2.** The working
    agreement requires persisting wizard state to the server or route, never
    localStorage. Steps 1–2 (policy + member, then claim type/admission
    type/hospital/dates/amount) happen before `POST /claims` exists to persist
    anything to — `policy`/`member` selections are lifted to URL search params
    (cheap id references), but the free-form fields in step 2 are not. A refresh
    before step 2's submit restarts intake at step 1; every step from 3 onward is
    fully resumable from `?claim={id}&step={n}` alone, since it all reads back from
    the server. Same shape of degradation `/policies/upload` already accepts for a
    refresh before its own upload begins — not a new kind of gap, just a new
    instance of it. See `DECISIONS.md`.

---

## 5. What's deliberately not built yet

Per `docs/claude-code-frontend-prompt.md` §10: Phase 2 (contracts, fixtures,
handlers, this document, the dev toolbar), Phase 3 (Features 5 and 1 — the
dashboard, policy list, upload/parse/review, policy detail, and grounded Q&A
screens), and Phase 4 (Features 6, 4, 2 — the claim list, claim wizard, claim
timeline, and eligibility) are done as of this document's current state.

Features 3 and 7 (bill validation, grievance drafting) and 8 and 9 (alerts inbox,
benchmarking) are not — `/alerts` and `/insurers` still render `PlaceholderScreen`.
The claim workspace's **Bill tab is a deliberate stub** this phase (per the Phase 4
brief) — it renders an `EmptyState` naming Phase 5, not a placeholder route; the
claim wizard's own bill-review step (4) shows a minimal read-only totals/flags
summary from the same `BillValidationReport` data, explicitly *not* the full
line-item table with source highlighting the brief describes for Feature 3 — that
polish is Phase 5's job, not duplicated ahead of time. The endpoints and fixtures
Phase 5/6 need (`/claims/{id}/grievance-drafts`, `/alerts`, `/insurers/benchmarks`,
`/ombudsman-awards`) already exist from Phase 2; only those screens are missing.
