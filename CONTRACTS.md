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

---

## 2. Endpoints

| # | Method & path | Request | Response | Notable errors | Sync / Job | Paginated | Idempotency-Key |
|---|---|---|---|---|---|---|---|
| 1 | `GET /health` | — | `{ status: "ok" }` | 401 | Sync | — | — |
| 2 | `POST /documents` | multipart: `file`, `claim_id` | 202 `JobAccepted` (kind `parse_document`) | 401, 413 (>25MB), 422 (bad type / missing file) | **Job**, 4–8s | — | **Required** |
| 3 | `GET /documents` | `?cursor&limit` | `Collection<StoredDocument>` | 401 | Sync | Cursor | — |
| 4 | `GET /documents/{id}` | — | `StoredDocument` | 401, 404 | Sync | — | — |
| 5 | `DELETE /documents/{id}` | — | 204 | 401, 404 | Sync (soft delete, D-20) | — | — |
| 6 | `GET /policies` | — | `Policy[]` | 401 | Sync | No (full array) | — |
| 7 | `POST /policies` | `{ source_document_id }` | `Policy` | 401, 409, 422 | Sync | — | — |
| 8 | `GET /policies/{id}` | — | `Policy` (embeds `coverage_profile`) | 401, 404 | Sync | — | — |
| 9 | `PATCH /policies/{id}/coverage-profile/fields/{field_path}` | `{ value, user_confirmed }` | `Policy` | 401, 404, 409, 422 | Sync | — | — |
| 10 | `POST /policies/{id}/questions` | `{ question }` | 202 `JobAccepted` (kind `answer_question`) | 401, 404 | **Job**, 3–6s | — | — |
| 11 | `GET /members` | — | `Member[]` | 401 | Sync | No (full array) | — |
| 12 | `GET /claims` | — | `Claim[]` | 401 | Sync | No — see §4 gap | — |
| 13 | `POST /claims` | `ClaimCreateRequest` | 201 `Claim` | 401, 422 | Sync | — | — |
| 14 | `GET /claims/{id}` | — | `Claim` | 401, 404 | Sync | — | — |
| 15 | `POST /claims/{id}/events` | `{ to_state, occurred_at, note }` | `Claim` (recomputed) | 401, 404, **409** (illegal transition — allowed targets in `field_errors`, see §3) | Sync | — | — |
| 16 | `POST /claims/{id}/eligibility` | — | `EligibilityAssessment` | 401, 404 | Sync | — | — |
| 17 | `POST /claims/{id}/completeness` | — | `CompletenessReport` | 401, 404 | Sync | — | — |
| 18 | `POST /claims/{id}/bill-validation` | — | `BillValidationReport` | 401, 404, **409** (bill not parsed yet) | Sync | — | — |
| 19 | `POST /claims/{id}/grievance-drafts` | `{ rung }` | 202 `JobAccepted` (kind `generate_grievance_draft`) | 401, 404 | **Job**, 20–30s | — | **Required** |
| 20 | `GET /alerts` | — | `Alert[]` | 401 | Sync | No (full array) | — |
| 21 | `GET /ombudsman-awards` | `?cursor&limit` | `Collection<OmbudsmanAward>` | 401 | Sync | Cursor | — |
| 22 | `GET /insurers/benchmarks` | — | `InsurerBenchmark[]` | 401 | Sync | No (full array) | — |
| 23 | `GET /jobs/{job_id}` | — | `Job<TResult>` | 401, 404 | Sync (this is what gets polled) | — | — |

23 endpoints. `#1` (`health`) is infra, not part of a vertical slice.

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
re-randomised per poll).

**Idempotency replay** stores the exact response body and status the first request
produced, keyed by the `Idempotency-Key` header value, and returns it byte-for-byte
on a repeat — no re-processing (`apps/web/mocks/db.ts`, `idempotencyStore`). This
mock doesn't expire the 24h window D-13 specifies (a page refresh clears the whole
mock DB anyway); a real backend must.

---

## 4. Ambiguous or underspecified — needs a decision or a ratified line

These are gaps found while building against `API_DECISIONS.md`, not places this
implementation disagrees with it. Each was resolved with a documented, reversible
assumption so Phase 2 could proceed; none should be read as settled.

1. **`Provenance.bbox` coordinate origin is unspecified.** Built in Phase 1 as
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

---

## 5. What's deliberately not built this phase

Per `docs/claude-code-frontend-prompt.md` §10, Phase 2 is contracts + fixtures +
handlers + this document + the dev toolbar — not screens. No route renders this data
yet (Phase 3 onward does). The `/kitchen-sink` primitives from Phase 1 haven't been
wired to live data either; that also starts in Phase 3.
