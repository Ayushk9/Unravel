# API Contract Decisions — Ratified

**Status:** Ratified for Phase 0–7 of the frontend build. Binding on all backend slices unless formally reversed.
**Scope:** Everything that crosses the FastAPI ↔ React boundary. Does not cover internal engine design.
**How to reverse a decision:** open a PR that edits this file, states the new ruling, and lists the blast radius from Section 7. Do not reverse a decision in code first.

These were resolved without full team review because frontend work was blocking on them. Every ruling below carries a **revisit trigger** — the concrete condition under which it should be reopened. If none of those conditions fire, treat the decision as settled and stop relitigating it.

---

## 1. Transport and shape

### D-01 · Versioned base path
All routes live under `/api/v1`. The frontend's `VITE_API_BASE_URL` points at the host only; `client.ts` appends `/api/v1`.

*Why:* Feature 9's ETL and Feature 2's rules will both change shape once real regulator data lands. A version prefix costs nothing now and prevents a breaking-change scramble mid-semester.
*Revisit:* never, within this project.

### D-02 · `snake_case` on the wire, both directions
JSON keys are `snake_case` in requests and responses. The frontend does **not** transform them.

*Why:* Pydantic emits `snake_case`. A camelCase translation layer is a second source of truth that nobody maintains, and it silently produces `undefined` when a field is renamed on one side only.
*Revisit:* never.

### D-03 · Response envelope
Single resources return the resource object directly — no `{data: ...}` wrapper.
Collections return:
```json
{ "items": [...], "next_cursor": null, "total": 12 }
```
`total` may be `null` for expensive counts.

Errors return exactly this, for every non-2xx response including FastAPI validation failures:
```json
{
  "error": {
    "code": "policy_not_found",
    "message": "No policy with that id belongs to your household.",
    "field_errors": [{ "field": "claim_type", "message": "must be cashless or reimbursement" }],
    "request_id": "01J8...",
    "retryable": false
  }
}
```

*Backend obligation:* FastAPI's default error body is `{"detail": ...}`. Install a global exception handler and a `RequestValidationError` handler that both emit the shape above. Do this in Phase 0 of the backend, not later — the frontend's error component is built against it.
*Why:* one error shape means one error component, one retry policy, and one place to surface `request_id` when a mentor asks why something failed during a demo.
*Revisit:* never.

### D-04 · Status codes

| Code | Used for |
| --- | --- |
| 200 | Successful read or synchronous write |
| 201 | Resource created, returned in body |
| 202 | Long-running job accepted — body contains `job_id` |
| 204 | Delete succeeded |
| 401 / 403 | Missing token / token valid but resource belongs to another household |
| 404 | Not found **or** not yours (see D-16) |
| 409 | Illegal state transition, or operation requires a parsed document that isn't parsed yet |
| 413 | Upload exceeds 25 MB |
| 422 | Request body failed validation |
| 429 | Rate limited (LLM quota) — include `Retry-After` |

*Note on 409:* it carries a machine-readable payload, because the UI uses it. For a bad claim transition, `error.code = "illegal_transition"` and `field_errors` lists the allowed target states so the UI can re-render the options without a second round trip.

### D-05 · Nulls are emitted, never omitted
Every field in the schema appears in every response. Unknown values are `null`.

*Why:* Feature 9 must distinguish "turnaround time is 14 days" from "the regulator did not publish it." If the key is missing, the frontend cannot tell "not reported" from "backend forgot." Do **not** use Pydantic's `exclude_none`.
*Revisit:* never.

### D-06 · Enums carry an escape hatch
Every string enum has an explicit `unknown` or `other` member on both sides. The frontend parses enums through a zod schema with `.catch("unknown")` so an added backend value degrades to a neutral rendering instead of a white screen.

*Why:* the document-type list and the alert-kind list will both grow during the semester. A frontend that crashes on an unrecognised enum makes the backend team afraid to add values, which is worse than the crash.

---

## 2. Long-running work

### D-07 · Job protocol, and exactly which endpoints use it

Anything that can exceed **two seconds** is a job. `POST` returns `202` with:
```json
{ "job_id": "01J8...", "kind": "parse_document", "status": "queued" }
```
The client polls `GET /api/v1/jobs/{job_id}`:
```json
{
  "job_id": "01J8...",
  "kind": "parse_document",
  "status": "queued | running | succeeded | failed",
  "progress": { "step": "extracting_tables", "percent": 45 },
  "result": { "document_id": "..." },
  "error": null
}
```

| Endpoint | Job or sync | Reasoning |
| --- | --- | --- |
| `POST /documents` (upload + parse) | **Job** | Docling on a 46-page scanned policy runs 10–40 s |
| `POST /policies/{id}/questions` (Feature 1 Q&A) | **Job** | Hybrid retrieve + rerank + Gemini ≈ 3–10 s |
| `POST /claims/{id}/grievance-drafts` (Feature 7) | **Job** | Generation plus decompose-and-verify ≈ 20–60 s |
| `POST /claims/{id}/eligibility` (Feature 2) | Sync | Deterministic rules over already-stored data, <300 ms |
| `POST /claims/{id}/bill-validation` (Feature 3) | Sync | Rules only; returns `409` if the bill document isn't parsed yet |
| `GET /insurers/benchmarks` (Feature 9) | Sync | ETL is offline; the endpoint reads precomputed analytics tables |
| `POST /claims/{id}/completeness` (Feature 4) | Sync | Set difference over already-classified documents |

*Polling policy (frontend):* every 1 s for the first 10 s, then every 3 s, hard timeout at 180 s with a "still working, come back later" state. Backend must keep terminal job records for 24 h so a page refresh can recover the result.

*Why this matters more than anything else in this document:* if the frontend is built assuming `POST /policies` returns a parsed policy synchronously, every screen that touches uploads has to be rebuilt when the real parser lands. This is the one contract mistake that costs weeks.
*Revisit:* if a job kind consistently completes under 500 ms in production, it may be demoted to sync — but only with a frontend PR in the same change.

### D-08 · Polling, not SSE or WebSockets
*Why:* Supabase free tier plus a single FastAPI process; polling is trivially debuggable and survives a proxy that buffers responses. SSE is a genuine upgrade, but it is not worth the connection-lifecycle code in a one-semester build.
*Revisit:* if parse jobs routinely exceed 60 s and users complain about the wait, revisit SSE for `progress` only.

---

## 3. Identity, ownership, and safety

### D-09 · Auth header present from day one
`Authorization: Bearer <token>` on every request, using Supabase Auth JWTs. The frontend sends a stubbed token in `VITE_API_MODE=mock`. MSW handlers assert the header exists.

*Why:* retrofitting auth means touching every endpoint and every hook. Sending a fake token costs one line now.

### D-10 · Ownership derives from the token, never from a parameter
There is no `household_id` query parameter anywhere. The server resolves the household from the JWT and scopes every query to it. A resource belonging to another household returns `404`, not `403`.

*Why:* passing identity as data is how a project ships an IDOR bug — anyone could enumerate `/policies/{uuid}` and read someone else's medical documents. Returning `404` rather than `403` also avoids confirming that a given id exists.
*Revisit:* never. This one is not negotiable even if it makes a demo harder.

### D-11 · Server-generated UUIDv7 ids
The client never generates resource ids. UUIDv7 (time-ordered) rather than UUIDv4, because Postgres B-tree indexes on random UUIDs fragment badly and the claim event log is append-heavy.

### D-12 · Timestamps and dates
- Instants: `timestamptz` in Postgres, stored UTC, serialized ISO-8601 **with offset** (`2026-03-01T09:15:00+05:30`).
- Calendar-only values (admission date, policy start date): `date`, no timezone, no time component.
- Display is IST throughout the UI.

*Why:* deadline arithmetic is the regulatory heart of Feature 6. Mixing naive and aware datetimes there produces off-by-one-day errors on exactly the deadlines that matter most.

### D-13 · Idempotency keys on two endpoints
`Idempotency-Key` header is **required** on `POST /documents` and `POST /claims/{id}/grievance-drafts`, and ignored elsewhere. The server stores key → response for 24 h and replays it on a repeat.

*Why:* both are expensive (storage; a Gemini call plus a verification pass) and both are the endpoints a user on a flaky mobile connection will double-submit. Every other write is cheap enough that a duplicate is a nuisance, not a cost.
*Revisit:* add to `POST /claims` if duplicate claims show up in testing.

---

## 4. Domain-specific rulings

### D-14 · `Extracted[T]` is a single generic model and is never flattened
Define once in `contracts/`:
```python
class Extracted(BaseModel, Generic[T]):
    value: T | None
    confidence: Literal["high", "medium", "low"]
    provenance: Provenance | None
    user_confirmed: bool = False
```
Every extracted field is wrapped. No endpoint ever returns a bare `sum_insured: 500000`.

*Why:* the product's entire credibility rests on being able to say where a number came from and how sure it is. If the wrapper is optional, some endpoint will drop it under deadline pressure, and the UI will render an unverified number as though it were confirmed.
*Revisit:* never.

### D-15 · Field correction is a targeted PATCH, not a whole-profile PUT
```
PATCH /api/v1/policies/{id}/coverage-profile/fields/{field_path}
Body: { "value": 500000, "user_confirmed": true }
```
`field_path` is a dotted path, e.g. `sub_limits.room_rent.cap_amount`, `waiting_periods.pre_existing.months`.

*Alternative considered and rejected:* `PUT` the whole coverage profile. Rejected because it forces the client to round-trip provenance for fields it did not touch (which it will eventually corrupt), and because two users correcting different fields would overwrite each other.
*Backend obligation:* a correction sets `user_confirmed: true` and **preserves the original provenance** plus the original extracted value in an audit column. The user's correction and the parser's output must both remain visible — that comparison is evaluation data for the report.

### D-16 · Claim state is a projection; clients append events
The client never writes `current_state`. It appends:
```
POST /api/v1/claims/{id}/events
Body: { "to_state": "denied", "occurred_at": "2026-03-01T00:00:00+05:30", "note": "..." }
```
The server validates against the state machine, appends to the immutable log, and returns the updated claim with the recomputed `current_state` and `deadlines`. Illegal transitions return `409` with the allowed targets.

*Why:* Feature 6's value is an auditable history. If the client can set state directly, the log becomes decorative.

### D-17 · Deadlines are computed server-side; the client only ticks
The server returns `due_at`, `days_remaining`, `basis`, and `urgency`. The client may run a live countdown, but it derives that countdown **from `due_at`**, and never computes `due_at` itself.

*Why:* a user's device clock being wrong must not change a statutory filing window. Duplicating the rule in TypeScript also guarantees the two copies diverge.

### D-18 · Direct multipart upload, not presigned Supabase URLs
`POST /api/v1/documents` accepts `multipart/form-data`, max 25 MB, `application/pdf` and common image types only.

*Why:* the backend needs the bytes anyway to enqueue parsing, so a presigned flow adds an upload-confirmation dance and a second failure mode for no gain at this size. Supabase free-tier storage is ~1 GB, which is ample for a capstone corpus.
*Revisit:* if real policy PDFs exceed 25 MB, or if the FastAPI host's request timeout becomes the bottleneck on slow campus uploads.

### D-19 · LLM response caching is invisible to the client
Grounded Q&A responses are cached by a hash of (retrieved chunk ids + normalised question) for 24 h. Grievance generation is **not** cached. Cache status appears in an `X-Cache: hit|miss` header for debugging only; the UI does not render it.

*Why:* Gemini free-tier quota is a real constraint during demo season, and Q&A is the endpoint a panel will hammer. Grievance drafts must not be cached because the underlying claim facts change between attempts.

### D-20 · Documents are soft-deleted; nothing else is
`DELETE /api/v1/documents/{id}` sets `deleted_at`. All other deletes are hard.

*Why:* "delete my documents" is a privacy expectation for medical records and needs to be recoverable from an accidental tap for a short window. Soft-deleting everything else just adds `WHERE deleted_at IS NULL` to every query for no benefit.

---

## 5. Pagination

| Resource | Paginated? | Style |
| --- | --- | --- |
| Documents | Yes | Cursor: `?cursor=&limit=` (default 20) |
| Claim events | Yes | Cursor, newest first |
| Ombudsman awards | Yes | Cursor |
| Policies, members, alerts, benchmarks | **No** | Full array |

*Why cursor over offset:* the event log and document list are append-heavy, and offset pagination on an append-heavy list skips or repeats rows as new items land. *Why some lists are unpaginated:* a household has under ten policies and under twenty alerts. Building pagination UI for a list that never paginates is dead code that still has to be tested.

---

## 6. Type ownership and enforcement

### D-21 · Hand-written TypeScript types are temporary
Until the backend exists, `packages/contracts-ts/types.ts` is hand-written and authoritative. From the moment the first FastAPI route ships, the flow inverts:

1. FastAPI generates `openapi.json`.
2. `openapi-typescript` generates `packages/contracts-ts/generated.ts`.
3. Generated types win. Hand-written duplicates are **deleted**, not kept in parallel.
4. CI runs `npm run generate:types && git diff --exit-code` — a drifted contract fails the build.

*Why:* two hand-maintained copies of the same types is the default failure mode of a split frontend/backend team, and it fails silently. Making CI the enforcement point matters because a written instruction is only context, not a guarantee — the check has to run.

### D-22 · Migrations have one owner
Alembic, one linear chain, no branching. The developer who owns Slice 1 (below) owns migrations; schema changes reach them by PR. Any change to `contracts/` must edit `CONTRACTS.md` in the same commit.

---

## 7. Vertical slice ownership

Frozen for the semester. Each slice owns its endpoints end to end — schema, service, route, tests.

| Slice | Owner | Engines | Endpoints | Depends on |
| --- | --- | --- | --- | --- |
| **1 — Ingestion & policy** | Migration owner | A, D (storage) | `POST /documents`, `GET /documents/*`, `GET/POST /policies`, coverage-profile reads, `PATCH .../fields/*`, `GET /jobs/*` | Nothing |
| **2 — Claims & rules** | | B, D (lifecycle) | `GET/POST /claims`, `POST /claims/{id}/events`, `/eligibility`, `/completeness`, `/bill-validation`, `GET /alerts`, the scheduled alert job | Slice 1's parsed line items and coverage profile |
| **3 — Retrieval & analytics** | | C, D (analytics) | `POST /policies/{id}/questions`, `POST /claims/{id}/grievance-drafts`, `GET /ombudsman-awards`, `GET /insurers/benchmarks` | Slice 1's document chunks |

**Week-one unblocking obligation on Slice 1:** ship the `documents`, `chunks`, and `coverage_profile` tables plus a fixture loader that seeds them from the frontend's mock fixtures, within the first week. Both other slices are blocked on real rows existing, and a fixture loader unblocks them without waiting for the parser to work.

**Frozen in week one, changeable only by PR to this document:** the `contracts/` package, and the `document` / `policy` / `claim` tables. Everything else may move freely inside its slice.

---

## 8. Open items — do not treat as settled

These need verification against primary sources before they appear in any demo, report, or panel presentation. Until verified, fixtures use obvious placeholders and the UI renders them with the estimate treatment.

| Item | Status | Where it bites |
| --- | --- | --- |
| Insurance Ombudsman award monetary ceiling (₹30 lakh vs ₹50 lakh across sources) | **Conflicting** — verify against the Ombudsman Rules as amended | Feature 7 rung selector; any eligibility copy |
| FY25 Council for Insurance Ombudsmen complaint count | **Unverified** | Problem-statement slide; Feature 9 framing |
| Ombudsman filing window from date of repudiation | **Unverified** | Feature 6 deadline rule — this one is load-bearing |
| Days of insurer silence before escalation is permitted | **Unverified** | Feature 6 deadline rule |
| Claim intimation deadline (varies by insurer) | **Do not hardcode** | Must come from the extracted policy, per-policy |

Rule: no regulatory number is hardcoded in application logic. Each lives in a versioned reference-data file with a source URL and a checked-on date, so the report can cite it and a stale value can be corrected in one place.
