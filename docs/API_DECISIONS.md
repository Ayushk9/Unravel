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
*Revisit:* **soon.** Real policies routinely have several `procedure` sub-limits, which this makes uncorrectable. The path needs a way to address one row (an id or a position).

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
- `ombudsman_precedent` is `[]` and the new `ombudsman_precedent_note` says why ("Precedent corpus not yet loaded ...").
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

**Update 2026-10-08:** the two deadline items above now have working values in `apps/api/app/rules/deadline_rules.yaml` (Ombudsman filing window: 1 year from denial; escalation after insurer silence: 30 days). They are a best understanding, marked `verified: false`, and are shown to users as unverified. They remain open until checked.

Rule: no regulatory number is hardcoded in application logic. Each lives in a versioned reference-data file with a source URL and a checked-on date, so the report can cite it and a stale value can be corrected in one place.
