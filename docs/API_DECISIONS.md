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

*Ruling, 2026-10-05:* the escape-hatch member for `SubLimit.cap_basis` and `WaitingPeriod.kind` is `"other"`, matching `packages/contracts-ts`. `contracts/models.py` now carries it for both. Engine A's internal LLM schema uses `"unknown"` for an undeterminable basis; that name is internal to the engine and never reaches the wire.

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
*Amended by D-42 for Q&A: the cache key and the absence of `X-Cache`.*
Grounded Q&A responses are cached by a hash of (retrieved chunk ids + normalised question) for 24 h. Grievance generation is **not** cached. Cache status appears in an `X-Cache: hit|miss` header for debugging only; the UI does not render it.

*Why:* Gemini free-tier quota is a real constraint during demo season, and Q&A is the endpoint a panel will hammer. Grievance drafts must not be cached because the underlying claim facts change between attempts.

### D-20 · Documents are soft-deleted; nothing else is
`DELETE /api/v1/documents/{id}` sets `deleted_at`. All other deletes are hard.

*Why:* "delete my documents" is a privacy expectation for medical records and needs to be recoverable from an accidental tap for a short window. Soft-deleting everything else just adds `WHERE deleted_at IS NULL` to every query for no benefit.

### D-23 · `Provenance.bbox` uses a top-left origin
`bbox` is `[x0, y0, x1, y1]`, normalised to 0..1 against the page's width and height, with the origin at the **top-left** corner of the page (y grows downward). Pages are 1-indexed. The same convention applies to `DocumentChunk.bbox`.

*Why:* this is what the web `DocumentViewer` draws and what Engine A emits (`engines/document/geometry.py` converts Docling's mixed origins). A mismatch does not crash; it mirrors every highlight vertically, which looks plausible and is wrong.
*Ratified:* 2026-10-05. Closes `CONTRACTS.md` §4 item 1.
*Revisit:* never.

### D-24 · `GET /health` is public
`GET /api/v1/health` returns `{ "status": "ok" }` without requiring an `Authorization` header. Every other route requires the bearer token (D-09).

*Why:* a health check exists so that something without credentials (an uptime probe, a deploy script, a developer with `curl`) can tell whether the process is up. Clients that send the header anyway are unaffected.
*Ratified:* 2026-10-05. Supersedes the `401` listed for this route in `CONTRACTS.md` §2 row 1.
*Revisit:* if the endpoint ever reports anything beyond liveness.

### D-25 · Policy identity fields are nullable
*Amended by D-46: the user may enter insurer, product and policy number.*
On `Policy`, the fields `insurer`, `policy_number`, `product_name`, `start_date` and `end_date` may be `null`. `policy_type` is never null; when unknown it is `"other"`. Clients must render a null as "not stated", not crash and not substitute a placeholder.

*Why:* a policy is created from an uploaded document, and Engine A does not extract these fields. A policy wording PDF often does not contain a policy number or dates at all (they are on the separate schedule). Sending an invented value would be a fact without provenance.
*Ratified:* 2026-10-07. Changes the previously non-null types in `packages/contracts-ts`.
*Revisit:* when Engine A extracts these fields; they should then become `Extracted[T]` rather than bare values.

### D-26 · Fetching a document's file: a short-lived signed URL
`GET /api/v1/documents/{id}/file` returns:
```json
{ "url": "https://...signed...", "expires_at": "2026-10-07T10:05:00Z" }
```
The route requires the bearer token and applies the usual ownership rule (another household's document is `404`). The returned `url` needs no token and is valid for 5 minutes. Clients must treat `url` as opaque and load it as given.

Where the URL points depends on the server's storage backend. With local-disk storage (the default, as the demo runs on one machine) it points back at this API, `GET /api/v1/local-files?path=…&expires=…&signature=…`, built on the host the client used to reach the API, and is protected by an HMAC signature. With Supabase storage it is a Supabase signed URL.

*Why:* a PDF viewer (pdf.js on web, a native viewer on Android) loads a plain URL far more easily than a request that needs an `Authorization` header, and file bytes never pass through the API host. The short lifetime bounds the damage if a URL leaks.
*Ratified:* 2026-10-07. New endpoint, `CONTRACTS.md` row 25.
*Revisit:* if a URL readable without a token is judged unacceptable for medical documents, switch to streaming the bytes through the API.

### D-27 · Reusing an Idempotency-Key with different content is a 409
Extends D-13. Keys are scoped to the household. A repeat of a key:

- with the **same** file (same SHA-256) returns the original `202` body unchanged and creates nothing;
- with a **different** file returns `409` with `error.code = "idempotency_key_reused"`.

A missing `Idempotency-Key` on an endpoint that requires it is `422` with a `field_errors` entry naming the header (ratifies `CONTRACTS.md` §4 item 7). Keys are remembered for as long as the job row exists, which is 24 h after the job finishes.

*Why:* silently replaying the first response for a different file would tell the client its second file was accepted when it was discarded.
*Ratified:* 2026-10-07.

### D-28 · `Job.error` is a sentence; `progress.step` values for `parse_document`
`Job.error` stays `string | null`: one sentence written for the user, never a stack trace and never the error envelope. The machine-readable code and whether a retry could succeed are stored server-side (`job.error_code`, `job.retryable`) and are not on the wire.

`progress.step` for a `parse_document` job takes these values, in order: `uploading`, `parsing_layout`, `extracting_fields`, `storing`, then `done`. `progress.percent` is a fixed marker per step, not a measurement.

*Why:* the wire type was already a string and both clients parse it as one. Step names are free-form strings by D-07, so adding names is not a breaking change.
*Ratified:* 2026-10-07.
*Revisit:* if a client needs to offer "try again" only for retryable failures, add `retryable` to the wire `Job`.

### D-29 · Upload rules for `POST /documents`
Extends D-18.

- Accepted types: `application/pdf`, `image/png`, `image/jpeg`. The server checks the file's leading bytes; a file whose contents do not match its declared type is `422`.
- PNG and JPEG uploads are accepted and stored, but cannot be parsed yet: their job fails with a message asking for a PDF.
- `claim_id` must be empty. A non-empty value is `422` until claim tables exist and ownership of the claim can be checked. An upload with no `claim_id` is treated as a policy document.
- A parse that runs longer than the server's limit (default 300 s) is stopped and its job fails. Note the web client stops polling after 180 s (D-07) and shows "still working"; a reload resumes polling.

*Ratified:* 2026-10-07.

### D-30 · Field correction: confirmed values only, and no guessing between rows
Extends D-15. The body must have `user_confirmed: true` and a non-null `value` of the field's type (integer paise for money; a number for percentages, months and hours); otherwise `422`. Correctable paths are exactly: `sum_insured`, `co_pay_percent`, `intimation_deadline_hours`, `sub_limits.<category>.cap_amount`, `waiting_periods.<kind>.months`. Any other path is `422`.

If a path matches more than one row (two sub-limits with the same category, or several waiting periods of the same kind), the response is `409` with `error.code = "ambiguous_field_path"` and nothing is changed.

*Why:* the mock edits the first matching row. On a real policy that can silently change the wrong number.
*Ratified:* 2026-10-07.
*Revisit:* resolved by D-41 (address a row by its position).

### D-31 · The claim state machine
Ratifies the graph that `CONTRACTS.md` §3 carried as a mock assumption:

```
intimated           -> documents_submitted, queried
documents_submitted -> under_review, queried
under_review        -> queried, approved, denied
queried             -> documents_submitted, under_review
approved            -> resolved
denied              -> escalated, resolved
escalated           -> resolved
resolved            -> (none)
```
It is defined once, in `apps/api/app/claims/state_machine.py`. An illegal transition, including an unknown `to_state`, is `409` with `error.code = "illegal_transition"` and one `field_errors` entry per allowed target, each `{ "field": "to_state", "message": "<state>" }` (ratifies `CONTRACTS.md` §4 item 5). A closed claim returns an empty list.

`POST /claims` writes the first event (`null -> intimated`) itself. `GET /claims` is a full array, not paginated (ratifies §4 item 3). `occurred_at` must carry a UTC offset and must not be in the future; it may be earlier than the previous event's, because people log letters late. Events are ordered by the server's sequence number, not by `occurred_at`.

*Ratified:* 2026-10-08.
*Revisit:* when Slice 2's owner reviews the lifecycle, in particular whether `escalated` needs splitting into "grievance filed with insurer" and "complaint filed with Ombudsman".

### D-32 · Concurrent transitions: one wins, the other gets 409
If two `POST /claims/{id}/events` requests race from the same state, exactly one event is written. The other request gets `409` with `error.code = "claim_changed"` and `retryable: true`; the client should reload the claim and let the user decide again. (If the second request is processed after the first has committed, it is judged against the new state and may instead get an ordinary `illegal_transition`.)

*Why:* the event log has `UNIQUE(claim_id, seq)`; both requests compute the same next `seq` and the database accepts one. No lock is taken.
*Ratified:* 2026-10-08.

### D-33 · Deadlines carry their source and whether the rule is verified
`Deadline` gains two fields, and `Claim` gains one:

```json
"deadlines": [{
  "id": "...", "label": "...", "due_at": "2027-08-10T23:59:59+05:30", "days_remaining": 355,
  "basis": "plain-language rule, with the date it was counted from", "urgency": "normal",
  "source": { "document": "Insurance Ombudsman Rules, 2017", "section": "...", "url": null },
  "verified": false
}],
"omitted_deadlines": [{ "id": "...", "label": "Claim intimation window", "reason": "..." }]
```

- `verified` is `false` until a person has checked the rule against its source. **Clients must mark an unverified deadline visibly.**
- `source` may be `null`; within it, `section` and `url` may be `null`.
- `omitted_deadlines` lists deadlines that apply but could not be computed (for example the policy's intimation window was not extracted), each with a reason. A missing input is never replaced by a guess.
- `due_at` is the end of the due date in India (`23:59:59+05:30`). `days_remaining` is due date minus today's date in India; `0` means due today. Urgency: below 0 `expired`, 0–3 `critical`, 4–14 `soon`, otherwise `normal`.

Rules live in `apps/api/app/rules/deadline_rules.yaml`, each with id, trigger, offset, description, source, `verified` and version. **As of ratification every rule is `verified: false`**; the values are a best understanding awaiting checking (see §8). No regulatory number appears in application code.

*Ratified:* 2026-10-08. Additive.

### D-34 · Documents on a claim, and how they are classified
Extends D-29. `POST /documents` accepts a `claim_id` owned by the caller; an unknown one is `422` on field `claim_id`. Such a document is **classified, not parsed**: one inexpensive model call on its first page yields `detected_type` (the contract's `DocumentType`, `unknown` when unrecognised) and a confidence. PDF, PNG and JPEG are all accepted for classification. The job's `result.policy_id` is `null`, and `progress.step` runs `uploading`, `classifying`, `storing`, `done`.

- `GET /documents?cursor&limit&claim_id` is keyset-paginated, oldest first; `cursor` is the `next_cursor` of the previous page; `limit` is 1–100, default 20 (ratifies §4 item 11).
- `PATCH /documents/{id}` with `{ "detected_type": ... }` records the user's label and sets `user_confirmed: true` (ratifies §4 item 10). The classifier's own answer and confidence are kept server-side for evaluation; `confidence` in the response is unchanged.
- `DELETE /documents/{id}` is a soft delete returning `204`.

*Note:* the classifier's confidence is reported by the model, unlike coverage fields, whose confidence is computed from how well a value matched the page.
*Ratified:* 2026-10-08.

### D-35 · Completeness reports explain the checklist and say whether it is verified
`CompletenessReport` gains:

```json
"required_details": [{ "type": "discharge_summary", "description": "...", "where_to_get": "...",
                       "source": { "document": "...", "section": null, "url": null } }],
"verified": false
```
`required_details` has one entry per item of `required`, in the same order. `missing = required − present`, where a document's type is the user's label if they set one, otherwise the classifier's. A document classified with low confidence still counts as present; `advisory_note` asks the user to check it. Documents typed `unknown`, still being read, or deleted do not count. A claim whose type has no checklist returns empty lists and says so.

The checklist lives in `apps/api/app/rules/required_documents.yaml` and is **`verified: false`** as of ratification. Clients must show that.

*Ratified:* 2026-10-08. Additive.

### D-36 · Eligibility checks show their working
`EligibilityCheck` gains three fields and `EligibilityAssessment` one; all additive:

```json
{
  "id": "ped_waiting_period", "title": "...", "status": "failed",
  "explanation": "Your policy started 14 Mar 2024; the 48-month waiting period ends on 14 Mar 2028. ...",
  "governing_clause": { "document_id": "...", "page": 2, "bbox": [...], "snippet": "..." },
  "missing_fact": null, "resolving_document": null,
  "confidence": "high",
  "values": { "policy_start": "2024-03-14", "waiting_months": 48, "waiting_period_ends": "2028-03-14",
              "admitted_on": "2026-04-02", "elapsed_months": 24, "elapsed_days": 19, "remaining_months": 23, "remaining_days": 12 },
  "missing_facts": [{ "fact": "...", "where_to_get": "...", "resolving_document": "investigation_report" | null }]
}
```
- `confidence` is the lowest confidence among the check's inputs (a user-confirmed input counts as `high`). It is a three-level label, **never a probability**.
- `values` holds the dates (`YYYY-MM-DD`), month and day counts and paise amounts the sentence was rendered from.
- `missing_facts` may list several facts, some resolved by a document outside `DocumentType` (`resolving_document: null`). `missing_fact` and `resolving_document` carry the first entry for older clients.
- `ombudsman_precedent` is `[]` and the new `ombudsman_precedent_note` says why ("Precedent corpus not yet loaded ..."). *Amended by D-45:* checked awards on the ground of a failed or at-risk check are listed.
- Status values stay `satisfied | at_risk | failed | unknown`.

**Band**, in strict precedence: `insufficient_information` if a critical check is unknown; else `likely_ineligible` if a check failed with high confidence; else `at_risk` if a check failed with lower confidence or is at risk; else `likely_eligible`. Critical checks: coverage profile, initial, pre-existing and condition-specific waiting periods, exclusions. A non-critical unknown is listed but does not prevent `likely_eligible`. Checks are ordered missing-facts-first for insufficient information, otherwise worst first.

Waiting periods: end = start + N calendar months, clamped to a shorter month's last day; an admission **on** the end date is outside the period; counted from `policy.start_date`, which is stated in every explanation as an assumption (first inception may be earlier). The rules are listed in `docs/RULES.md`, generated from `engines/rules/registry.py`.

*Ratified:* 2026-10-15. Additive.

### D-37 · Claim facts the rules read
New: `PUT /api/v1/claims/{id}/facts`, a full replacement, returns the `Claim`. `Claim` gains `facts`:

```json
"facts": {
  "diagnosis": "Complications of type 2 diabetes",   // display only; no rule reads it
  "condition_is_pre_existing": true,                 // strict boolean or null
  "first_diagnosed_on": "2023-11-05",                // not in the future
  "matched_waiting_periods": [2],                    // positions in coverage_profile.waiting_periods
  "matched_exclusions": [],                          // positions in coverage_profile.exclusions
  "planned_room_rent_per_day": 450000                // integer paise
}
```
`null` means not answered; the rule that needs it returns `unknown`. `[]` means none apply. A `matched_waiting_periods` entry must point at a `disease_specific` period; positions must exist and not repeat; otherwise `422`. Whether an illness falls under a listed condition or exclusion is decided only by this selection, never by keyword matching or a model. The time the insurer was told comes from the existing `intimated` event.

*Ratified:* 2026-10-15. Additive.
*Revisit:* if positions prove fragile, give waiting periods and exclusions stable ids.

### D-38 · Alerts say whether they rest on verified figures
`Alert` gains `verified: boolean` and `provenance: Provenance | null`. `verified` is `false` when the alert relies on a reference figure nobody has checked (these alerts also say "estimate" in their text). `provenance` points at the policy field the alert is based on, and is `null` when the alert is about something not being found. `Alert.id` is a deterministic string such as `alert-low_sum_insured-<policy_id>`, not a UUID.

Alerts are computed on every `GET /alerts` for the household's policies; nothing is stored or scheduled. An alert whose input is missing (policy dates, sum insured, the household's city, which is never stored yet) is skipped and the reason logged; `GET /alerts` stays a bare array.

*Ratified:* 2026-10-15. Additive.

### D-39 · Policy dates are entered by the user, including the start of continuous cover
New: `PATCH /api/v1/policies/{id}` with any of `start_date`, `end_date`, `first_inception_date` (`YYYY-MM-DD`). Only the keys sent change; a key sent as `null` clears that date; an empty body is `422`. Returns the `Policy`. `Policy` gains `first_inception_date: date | null`.

- Checked as a whole after the change: `end_date` must be after `start_date`; `first_inception_date` must be on or before `start_date` and not in the future. Any violation is `422` naming the field, and nothing is changed.
- These are plain dates, not `Extracted[T]`: the user typed them; nothing was read from a page, so there is no provenance to show and none is invented. When Engine A extracts them (D-25's revisit), extracted values become `Extracted[T]`.
- **Waiting periods are counted from `first_inception_date` when it is set, otherwise from `start_date`.** This applies to the eligibility checks, to `waiting_periods[].starts_on / expires_on`, and to the waiting-period alert. In a check's `values` the date appears as `first_inception_date` or `policy_start`, naming which one was used, and the explanation says so ("Your continuous cover started ..." vs "Your policy started ..." plus the stated assumption).

*Why:* uploaded policies had no way to get dates (D-25), so every waiting-period check on them was `unknown`. And a renewed policy's waiting periods run from the first policy, not the current one.
*Ratified:* 2026-10-15. Additive.
*Revisit:* when Engine A extracts the dates from a policy schedule.

### D-40 · The household chooses its kind of city
New: `GET /api/v1/household` returns `{ "id", "name", "city_tier" }`; `PATCH /api/v1/household` takes `{ "city_tier": "metro" | "tier_2" | "other" | null }` (the key is required; `null` clears it) and returns the `Household`. Any other value or any other key is `422`. There is no household id in the path (D-10).

`city_tier` is the household's own choice; the server keeps no list of which cities are metros. The `room_rent_below_market` alert now runs when it is set: it fires (severity `info`) when the policy's room-rent cap per day is below the typical rate for that tier in `engines/rules/reference/typical_costs.yaml`. Those figures are **`verified: false`**, so the alert says "estimate" and carries `verified: false`; its `provenance` is the room-rent clause. `other`, no tier, or no single per-day cap means the alert is skipped and the reason logged.

*Why:* a tier, not a city name: the reference data has figures per tier, and a free-text city would need a mapping nobody has checked.
*Ratified:* 2026-10-15. Additive.

### D-41 · A list row is corrected by its position
Extends D-30. `PATCH /policies/{id}/coverage-profile/fields/{field_path}` also accepts `sub_limits.<position>.cap_amount` and `waiting_periods.<position>.months`, where `<position>` is the 0-based index of the row in that list exactly as `GET /policies/{id}` returns it (plain digits only). A position always names one row, so it never gives `ambiguous_field_path`. A position past the end of the list is `422` on `field_path`.

The category / kind form (`sub_limits.room_rent.cap_amount`) still works and is still `409 ambiguous_field_path` when two rows share it; that error's message now says to use a position. The web client sends positions for every list row.

*Why:* closes D-30's revisit. Positions are what D-37 already uses for the same lists, so a client addresses a row the same way everywhere.
*Ratified:* 2026-10-16. Additive.
*Revisit:* if rows get stable ids (D-37's revisit), address by id instead.

### D-42 · Policy Q&A: request, result, verification and caching
Specifies `POST /api/v1/policies/{id}/questions` (CONTRACTS.md row 11), whose job result was never pinned down.

**Request:** `{ "question": string }`, 1–500 characters after trimming, otherwise `422`. Any language; Hindi and Marathi are recognised by their script. Errors:
- another household's policy, or an unknown one, is `404`;
- a policy that has not been read and indexed yet (no stored clauses, or clauses without search vectors) is `409` with `error.code = "policy_not_indexed"`, per D-04.

Otherwise `202 JobAccepted` with `kind: "answer_question"`. No `Idempotency-Key` (D-13 unchanged).

**Progress:** `progress.step` runs `retrieving`, `generating`, `verifying`, then `done`.

**Result** (`Job.result` when `succeeded`) is `QuestionAnswerResult` plus one additive field:
```json
{
  "answer": "Your policy caps room rent at Rs 5,000 per day. [[1]] ...",
  "citations": [{ "id": "<chunk id>", "kind": "policy_clause", "label": "Page 2",
                  "provenance": { "document_id": "...", "page": 2, "bbox": [0.1, 0.2, 0.6, 0.23], "snippet": "..." },
                  "external_url": null }],
  "abstained": false,
  "missing_context": null,
  "verification": { "sentences_checked": 3, "sentences_removed": 1 }
}
```
- **Citation markers (ratifies CONTRACTS §4 item 9):** `answer` is a sequence of sentences, each followed by one or more `[[n]]` markers, where `n` is the 1-indexed position in `citations`. Every citation is referenced at least once. Each citation is one clause (chunk) of the policy's own document, with its page and normalised bbox (D-23), so a client opens the exact clause.
- **Verification:** every generated sentence is checked before it is sent.
  - Every number in it must appear in a cited clause or in the user's own question.
  - A second model call must judge at least one cited clause to support it.
  - A sentence that fails is **left out of `answer`**; its text is never sent. `verification` reports how many sentences were checked and how many were removed, so a client can say so.
  - A citation judged not to support its sentence is dropped.
- **Abstention:** `abstained: true`, `answer: ""`, `citations: []` and `missing_context` set to a sentence. This happens when the clauses don't answer the question, or when no sentence survives verification. Abstention is a normal result, not an error.
- **Language:** answers are in English whatever the question's language. A non-English question is rewritten into English search terms for retrieval only; the original question is stored unchanged.

**Caching (amends D-19):** a result is cached for 24 h, keyed by the document id, the document's SHA-256, the normalised question, the prompt version and the configured model. A hit makes no model call at all. The document id is in the key because a cached result names its document and clause ids: the same file uploaded again, or by another household, is a different document and never receives another document's answer (corrected 2026-10-19; the first version keyed on the hash alone).

**When Gemini is busy (2026-10-19):** a 503 or 429 is retried up to 4 attempts with exponential backoff and full jitter (waits drawn from 0–2 s, 0–4 s, 0–8 s). A 429 whose retry delay is over 60 s (a used-up daily quota) is not retried. Then `GEMINI_FALLBACK_MODEL`, if set, gets one try. Which model answered each call is stored with the cached answer and in the question log. If every try fails the job fails with `error` = "The answering service is busy right now. Please try again in a minute." and, server-side, `error_code = "llm_overloaded"` or `"llm_rate_limited"`, `retryable = true` (D-28: neither is on the wire). There is no `X-Cache` header: the answer arrives through `GET /jobs/{id}`, not the response that queued it. Hit or miss is recorded server-side.

**Parse progress (amends D-28):** a policy parse gains a step `indexing` between `storing` and `done`. Indexing failure does not fail the parse; questions on that policy are `409 policy_not_indexed` until it is re-indexed.

*Ratified:* 2026-10-16. Additive except the D-19 amendment.
*Revisit:* when grievance drafting (Feature 7) reuses the marker convention.

### D-43 · Grievance drafts: who writes what, and which rungs fit now
Specifies the result of `POST /api/v1/claims/{id}/grievance-drafts` (CONTRACTS.md row 20) and adds `GET /api/v1/claims/{id}/grievance-rungs` (row 30).

**`GrievanceDraft` gains** (additive):
```json
{
  "addressee": "The Grievance Redressal Officer, Star Health and Allied Insurance",
  "header_lines": [{ "label": "Policy number", "value": null }, ...],
  "closing": "I request you to review this claim ... Enclosures: ... Yours faithfully, ...",
  "disclaimer": "This is a draft based on your documents, not legal advice. ...",
  "letter_text": "To, ... (the whole letter as plain text)",
  "missing_context": null,
  "generated_at": "2026-10-20T10:00:00+00:00"
}
```
- **Only `paragraphs[].text` is written by a model.** `subject`, `addressee`, `header_lines` (patient, insurer, policy number, plan, hospital, admission and discharge dates, amount claimed from paise, denial date, and the denial reason quoted from the `denied` event's note), the pages cited, `evidence_checklist`, `closing`, `disclaimer` and `letter_text` are built by server code from stored data. A fact that is not recorded is `null` (shown as "not recorded"), never a placeholder that looks real.
- **Paragraphs cite policy clauses only** (`kind: "policy_clause"`, with page and bbox, D-23). Claim documents are classified, not read (D-34), so there is no text to check a citation of them against; they appear in the evidence checklist and the enclosures instead.
- **Verification as in D-42, but nothing is removed.** Every paragraph gets the number check (its numbers must be in a cited clause or in the claim facts given to the model) and the support judge. A paragraph that fails either is **kept with `verified: false`** and clients must flag it visibly (product rule 4); `letter_text` prefixes it with a warning line. A verified paragraph keeps only the citations judged to support it; an unverified one keeps all it cited. `citation_precision` = verified paragraphs / all paragraphs.
- **No paragraph** (nothing retrieved, or the model found no honest ground): `paragraphs: []`, `citation_precision: 0`, `missing_context` is our own sentence, and the header, checklist and closing are still returned; `letter_text` asks the user to write their own reasons. A normal result, not an error.
- **No `[[n]]` markers** in paragraph text (closes D-42's revisit for grievances): each paragraph carries `citation_ids`, and markers would end up in the copied letter.
- `progress.step` runs `retrieving`, `drafting`, `verifying`, `done`. Drafts are never cached (D-42). Gemini failures are handled as in D-42 ("The drafting service is busy right now. Please try again in a minute.").
- No regulatory figure appears in a letter. The Ombudsman's award limit is in `apps/api/app/rules/ombudsman_rules.yaml` with `value: null, verified: false` and is read into no output (§8).

**`GrievanceRungOption`** (`GET /claims/{id}/grievance-rungs`, one per rung in ladder order):
```json
{ "rung": "insurance_ombudsman", "label": "Insurance Ombudsman", "available": true,
  "reason": "Your claim was denied on 2 May 2026. A complaint to the Insurance Ombudsman can be made until 2 May 2027. ... This is based on a rule that has not yet been checked against its source.",
  "rule_ids": ["ombudsman_filing"], "verified": false }
```
Computed on read by a pure function from the claim's state, its events and its deadlines (D-33), with the rungs described in `apps/api/app/rules/grievance_rungs.yaml`. A rung is `verified` only if its own description and the deadline rule it uses are both verified; **as of ratification none is**. An unverified rung is still offered, and marked. An expired window is still offered, saying it "may have passed", because the rule behind it is unchecked.

*Ratified:* 2026-10-20 (Phase 7 plan approval). Additive.
*Revisit:* when the rung rules are verified; when claim documents are read (they could then be cited).

### D-44 · Errors of `POST /claims/{id}/grievance-drafts`
Extends row 20, all consistent with D-04 and D-27:
- `422`: a missing `Idempotency-Key` (field `Idempotency-Key`); a `rung` that is not one of the three, including `"other"` (the escape hatch exists for responses, not requests).
- `409 idempotency_key_reused`: the same key with a different `rung`. The same key with the same rung replays the first 202.
- `409 rung_not_available`: the rung does not fit the claim's current state (for example the Ombudsman for a claim that is only `intimated`). `field_errors` has one `{ "field": "rung", "message": "<rung>" }` per rung that is available, like `illegal_transition` (D-31).
- `409 policy_not_indexed`: the claim's policy has no searchable clauses yet (as D-42).

*Ratified:* 2026-10-20. Additive.

### D-45 · Ombudsman awards: checked by a person, ids, and matching by ground
- Awards live in `engines/rules/reference/ombudsman_awards.yaml`, **filled only by Ayush from published awards**. An entry is served (by `GET /ombudsman-awards` and as eligibility precedent) only when `checked_by_ayush: true`. It is empty at ratification.
- `id` is `uuid5(fixed namespace, case_reference)`: stable across restarts, which cursors and links need. A deliberate exception to server-generated UUIDv7 ids (D-11): these are reference rows, not resources a client creates.
- `denial_ground` in the file is a tag, one of Engine B's eligibility check ids (`ped_waiting_period`, `permanent_exclusions`, ...); an unknown tag stops the file loading. On the wire `denial_ground` is that check's plain title ("Pre-existing disease waiting period"), so the `OmbudsmanAward` shape is unchanged.
- `ombudsman_precedent` on an eligibility assessment lists the checked awards whose tag is the id of a check that is `failed` or `at_risk` on this claim: an exact match, with no keywords, no similarity score and no model. `ombudsman_precedent_note` is one of three fixed sentences (none loaded / none on this ground / these match), each saying the awards are not a prediction of how the claim will be decided.
- `GET /ombudsman-awards`: newest `decided_on` first; `cursor` is the id of the last award seen; an unknown cursor is `422` on `cursor`.

*Ratified:* 2026-10-20. Additive.

### D-46 · Policy identity is entered by the user, and marked as such
Extends D-39 and amends D-25. `PATCH /api/v1/policies/{id}` also accepts `insurer_name`, `product_name` and `policy_number`: a string, trimmed, 1–200 characters, or `null` to clear. Every D-39 rule still holds: only the keys sent change, an empty body is `422`, and the dates are checked as a whole.

`Policy` gains two fields (additive):
```json
"insurer_name": "Star Health and Allied Insurance Co. Ltd.",
"user_entered_fields": ["insurer_name", "product_name", "policy_number", "start_date", "end_date", "first_inception_date"]
```
- `insurer_name` is the user's text, stored on the policy. The shared `insurer` table (reference data every household sees) is never written from user input; `insurer` stays `null` unless we link a reference insurer. Clients show `insurer.name` when set, else `insurer_name`, else "not stated".
- `user_entered_fields` names which of those six fields the user typed. Setting a field adds it; clearing it (`null`) removes it. These are plain values, not `Extracted[T]`: nothing was read from a page, so no provenance is invented. Clients mark each one "Entered by you". Dates set before this decision were marked by migration 0009 (PATCH was the only way to set them).
- Grievance letters (D-43) use them. The addressee is exactly "Grievance Redressal Officer, <insurer>" (`insurer.name`, else `insurer_name`, else "your insurer"), **never with an address, e-mail or phone number**. The "Plan" and "Policy number" header lines use the entered values.

*Ratified:* 2026-10-20. Additive.
*Revisit:* when Engine A extracts these fields from a schedule (they then become `Extracted[T]`, D-25's revisit).

### D-47 · Fixed procedural requests in a grievance draft
Extends D-43. Approved by Ayush, 2026-10-22.

- `DraftParagraph` gains `source`: `"model"` (written by the model and checked, as before) or `"template"` (our fixed text, no model output), with `"other"` as the escape hatch (D-06).
- `GrievanceDraft` gains `assessment_note: string | null`.
- **When:** if no model paragraph survived verification (none written, all unverified, nothing retrieved), or our rules agree with the denial, three fixed requests are added after the model's paragraphs. They ask the insurer to (a) state the exact clause relied on, (b) share the evidence used, and (c) give a written, reasoned decision.
- A template paragraph has `citation_ids: []` and `verified: false`: it is a request, not a claim, and nothing was checked. Clients show it as template text, not as an unconfirmed claim. A client that doesn't know `source` falls back to flagging it, which is the safe failure. `letter_text` doesn't mark it.
- `citation_precision` counts **model** paragraphs only.
- **"Our rules agree"** means the eligibility band is `likely_ineligible` (a check failed with high confidence, D-36). The recorded denial reason is free text and is never keyword-matched. So this can't confirm that the failed check is the very ground the insurer named; it says our assessment also finds the claim likely ineligible.
- Then `assessment_note` is exactly "Our assessment agrees with the insurer's stated reason. This letter asks the insurer to explain its decision; it does not dispute it.", and clients show it with the letter. The subject becomes "Request for an explanation of the denial …" and the closing asks for a written reply to each point instead of a review. Otherwise `assessment_note` is `null`.

*Clarified 2026-10-23:* when a draft has no `source: "model"` paragraph, `citation_precision` is still sent as `0` (the field stays a number, so no client breaks), but it is not a score. Clients show "No model-written paragraphs to check" instead of a figure.

*Ratified:* 2026-10-22. Additive.

### D-48 · The denial ground, a rules-built opening, and "Before you send"
Extends D-37, D-43 and D-47. Approved by Ayush, 2026-10-22.

- **`ClaimFacts.denial_ground`**: an eligibility check id (`ped_waiting_period`, `initial_waiting_period`, …, the same tags as D-45), or `null` (not answered). The user chooses it from the insurer's letter; the free-text note on the `denied` event is never read for it. It defaults to `null`, so a client that doesn't send it still validates (and, as a full replacement, clears it). An unknown id is `422`.
- **D-47's "our rules agree" becomes exact:** with a ground chosen, it means that check failed. Without one, the D-47 band rule still applies.
- **A rules-built opening paragraph** (`DraftParagraph.source = "rules"`): when the chosen ground's check is a date-counted waiting period and is **satisfied**, the letter opens with fixed text built only from that check's `values`:
  - the date cover counts from (first inception when entered);
  - the period's length and its end date;
  - the admission date.

  It cites the check's governing clause (page and bbox), so its citation id is `rule-<check id>` rather than a clause id. It is `verified: false` (no model check ran; a client that doesn't know `source` flags it, the safe failure), is not marked in `letter_text`, and is not counted in `citation_precision`. A missing value means no paragraph, never a guess. With an opening, the letter counts as arguing: no D-47 templates for "nothing survived", and no `missing_context`.
- **`GrievanceDraft.before_you_send`**: a list of `{text, citation_ids, source: "rules" | "model" | "other", verified}`. Shown on the screen; **never in `letter_text`**.
  - `rules` notes come from the same check: the date cover is counted from, and whether the period's length is confirmed.
  - `model` notes are conditions the model found in the clauses it was given that the insurer could rely on (for example "must have been declared at application"). They come from the same draft call and are checked by the same number check and judge call as paragraphs; one that fails is kept with `verified: false` and flagged.
- **Prompt (grievance-v4, then the judge fix):** the model may argue only from the claim's facts and the checks that **support** the policyholder (only satisfied checks are given to it). It must not introduce optional covers, portability or other benefits the facts don't mention, and must not raise conditions against the policyholder in the letter; those go to `conditions`.

*Ratified:* 2026-10-22. Additive.
*Revisit:* when grounds other than waiting periods need a fixed paragraph.

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
| Insurance Ombudsman award monetary ceiling | **Resolved 2026-10-23 (verified by Ayush):** ₹50 lakh, including relevant expenses. Insurance Ombudsman Rules, 2017 (as amended till 09.11.2023), Rule 17(3) proviso (ii), substituted by G.S.R. 828(E) dated 9.11.2023 ([source](https://www.cioins.co.in/notification/Insurance%20Ombudsman%20Rules,%202017(%20as%20amended%20till%2009.11.2023).pdf)). `ombudsman_rules.yaml` `verified: true`. Shown only in the Ombudsman rung's reason, as a limit on what can be awarded, never as a promise; never in a letter | Feature 7 rung selector |
| FY25 Council for Insurance Ombudsmen complaint count | **Unverified** | Problem-statement slide; Feature 9 framing |
| Ombudsman filing window | **Window verified 2026-10-23: 1 year, Rule 14(3)(b). Trigger wrong in our rules:** by Rule 14(3)(a) the year runs from the insurer's reply to a written grievance, or from one month after the grievance if there is no reply, not from the denial. The rule stays `verified: false` until the correction (the D-49 plan) is approved and built | Feature 6 deadline rule; Feature 7 Ombudsman rung |
| Days of insurer silence before escalation is permitted | **Verified 2026-10-23 as part of Rule 14(3)(a): one month** after the written representation with no reply. Built into the D-49 plan; `escalation_eligibility` stays unverified until then | Feature 6 deadline rule |
| Insurer decision deadline | **Not verified, being confirmed (2026-10-23):** IRDAI/HLT/REG/CIR/152/06/2020 (30 days from the last necessary document, 45 if investigated, interest at bank rate + 2%) vs the Master Circular IRDAI/PP&GR/CIR/MISC/117/9/2024 of 5 Sep 2024 (appears to set 15 days from submission for non-cashless health claims). Value unchanged (30 days), `verified: false` | Feature 6 deadline rule |
| Claim intimation deadline (varies by insurer) | **Do not hardcode** | Must come from the extracted policy, per-policy |

**Update 2026-10-08:** the two deadline items above now have working values in `apps/api/app/rules/deadline_rules.yaml` (Ombudsman filing window: 1 year from denial; escalation after insurer silence: 30 days). They are a best understanding, marked `verified: false`, and are shown to users as unverified. They remain open until checked.

Rule: no regulatory number is hardcoded in application logic. Each lives in a versioned reference-data file with a source URL and a checked-on date, so the report can cite it and a stale value can be corrected in one place.
