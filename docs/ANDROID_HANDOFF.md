# Android handoff: Unravel API

For the Android developer building the second client of the Unravel API.

Everything below was checked against the backend code on branch `feat/backend-v2`
(commit `5fd97ea`, 2026-10-14), not just against the docs. Where the code and
`CONTRACTS.md` disagree, the code is described here and the disagreement is listed
in §9.

Binding references, in order of authority:

1. `docs/API_DECISIONS.md`: ratified rulings (D-01 … D-35).
2. `CONTRACTS.md`: the endpoint table (see §9 for where it is stale).
3. `packages/contracts-ts/src/types.ts`: the domain types, hand-written. Mirror these
   in Kotlin.

---

## 0. Rules that apply to every request

| Rule | Detail |
| --- | --- |
| Base path | Every route is under `/api/v1` (D-01). |
| Casing | JSON is `snake_case` both ways. Do not configure a camelCase naming strategy on the wire (D-02). |
| Nulls | Every field is present in every response; unknown is `null`, never a missing key (D-05). Model nullable fields as nullable, not as optional-with-default. |
| Request bodies | The server also expects every key in a request body, even nullable ones. Send `"note": null`, don't omit `note` (see §4). Unknown keys are rejected with `422` (`extra="forbid"`, `apps/api/app/schemas/base.py`). |
| Money | Integer **paise** (`Long` in Kotlin). ₹5,000 = `500000`. Never float. `claimed_amount: 5000.5` or `"5000"` is a `422`. |
| Ids | Server-generated UUIDv7 strings. Treat as opaque strings. (Mock fixtures use readable ids like `claim-denied-ped`; the real server never does.) |
| Instants | ISO-8601 with offset, e.g. `2026-10-14T10:05:00Z` or `2026-03-01T09:15:00+05:30`. Requests must include an offset. |
| Dates | Calendar dates are `YYYY-MM-DD` with no time (D-12). |
| Enums | Every enum has an escape hatch (`"unknown"` or `"other"`). Parse unknown values to that member instead of crashing (D-06). |
| `Extracted<T>` | `{ value, confidence, provenance, user_confirmed }`. Never flattened (D-14). See §3. |
| Auth | `Authorization: Bearer <token>` on every route except `GET /health` and the signed `GET /local-files` link (§2). |
| Ownership | No endpoint takes a `household_id`. Another household's resource is `404`, not `403` (D-10). |
| Request id | Every response has an `X-Request-ID` header (UUIDv7). Error bodies repeat it as `error.request_id`. Log it; it's what the backend dev needs to find a failure. |

### The error envelope

Every non-2xx response, including validation errors, unknown routes and 500s, has
exactly this body (built in `apps/api/app/core/errors.py`):

```json
{
  "error": {
    "code": "validation_error",
    "message": "The request was not valid.",
    "field_errors": [{ "field": "claimed_amount", "message": "Input should be a valid integer" }],
    "request_id": "01a13a10-b6f8-7c5c-bda7-f6d47a24c876",
    "retryable": false
  }
}
```

`field_errors` is always an array (often empty). For FastAPI validation errors the
`field` is the dotted path without the `body.`/`query.` prefix (e.g. `items.0.amount`).

Error codes the implemented routes actually emit:

| Status | `code` | When |
| --- | --- | --- |
| 401 | `unauthorized` | Missing header, wrong scheme, or invalid/expired token. Has `WWW-Authenticate: Bearer`. |
| 403 | `no_household` | Token is valid but the user has no household (e.g. dev DB not seeded). |
| 403 | `link_not_valid` | A `/local-files` link is wrong or expired (§2). |
| 404 | `not_found` | No such resource, someone else's resource, or an unknown route. |
| 405 | `method_not_allowed` | Known path, wrong method. Note: `POST /policies` returns this today, because it isn't implemented but `GET /policies` is. |
| 409 | `illegal_transition`, `claim_changed`, `claim_has_no_history` | Claim events (§4). |
| 409 | `idempotency_key_reused` | Same `Idempotency-Key`, different file (D-27). |
| 409 | `profile_not_ready`, `ambiguous_field_path` | Field correction (D-30). |
| 413 | `file_too_large` | Upload over 25 MB. |
| 422 | `validation_error` | Any bad input. |
| 500 | `internal_error` | A bug. Message is generic; quote the `request_id`. |
| 503 | `storage_unavailable`, `auth_unavailable` | Transient. `retryable: true`. |

---

## 1. Endpoints

### 1a. Implemented and working now (18 routes)

This list is the server's own OpenAPI route table (`app.openapi()`), not the docs. The
full API test suite passed against a real Postgres on 2026-10-14
(`395 passed`, including all database-backed tests).

All bodies are JSON unless stated. "Auth" = bearer token required.

#### Infra

| Method & path | Auth | Request | Response |
| --- | --- | --- | --- |
| `GET /health` | **No** (D-24) | — | `200 { "status": "ok" }` |

#### Pipeline: policies and upload (Slice 1)

| Method & path | Request | Response | Errors |
| --- | --- | --- | --- |
| `POST /documents` | `multipart/form-data`: `file` (required), `claim_id` (optional form field). Header **`Idempotency-Key` required** (≤255 chars). | `202 JobAccepted` | 401, 409 `idempotency_key_reused`, 413, 422 (missing key, missing file, bad type, contents don't match declared type, unknown `claim_id`), 503 |
| `GET /jobs/{job_id}` | — | `200 Job` | 401, 404 |
| `GET /documents` | Query: `cursor` (UUID, optional), `limit` 1–100 (default 20), `claim_id` (UUID, optional) | `200 Collection<StoredDocument>`, oldest first | 401, 422 |
| `GET /documents/{id}` | — | `200 StoredDocument` | 401, 404 |
| `PATCH /documents/{id}` | `{ "detected_type": DocumentType }` | `200 StoredDocument` | 401, 404, 422 |
| `DELETE /documents/{id}` | — | `204`, no body (soft delete, D-20) | 401, 404 |
| `GET /documents/{id}/file` | — | `200 { url, expires_at }` (see §2) | 401, 404, 503 |
| `GET /local-files` | Query: `path`, `expires`, `signature` (you never build this; it's the `url` above) | `200` file bytes | 403 `link_not_valid`, 404 |
| `GET /policies` | — | `200 Policy[]` (full array, not paginated) | 401 |
| `GET /policies/{id}` | — | `200 Policy` | 401, 404 |
| `PATCH /policies/{id}/coverage-profile/fields/{field_path}` | `{ "value": number, "user_confirmed": true }` | `200 Policy` (whole updated policy) | 401, 404, 409 `profile_not_ready` / `ambiguous_field_path`, 422 |
| `GET /members` | — | `200 Member[]` (full array) | 401 |

#### Pipeline: claims (Slice 2, lifecycle and completeness only)

| Method & path | Request | Response | Errors |
| --- | --- | --- | --- |
| `GET /claims` | — | `200 Claim[]`, oldest first, full array | 401 |
| `POST /claims` | `ClaimCreateRequest` | `201 Claim` | 401, 422 (unknown `policy_id`/`member_id`, `discharged_on` before `admitted_on`, non-integer amount) |
| `GET /claims/{id}` | — | `200 Claim` | 401, 404 |
| `POST /claims/{id}/events` | `{ to_state, occurred_at, note }` | `200 Claim` (recomputed state and deadlines) | 401, 404, 409, 422 |
| `POST /claims/{id}/completeness` | no body | `200 CompletenessReport` | 401, 404 |

#### Shapes

```text
JobAccepted   { job_id: UUID, kind: "parse_document", status: "queued" }

Job           { job_id, kind: "parse_document"|"answer_question"|"generate_grievance_draft",
                status: "queued"|"running"|"succeeded"|"failed",
                progress: { step: string, percent: int } | null,
                result:   { document_id: UUID, policy_id: UUID|null } | null,
                error:    string | null }        // one user-facing sentence (D-28)

Collection<T> { items: T[], next_cursor: string|null, total: int|null }

StoredDocument { id, file_name, mime_type, page_count: int, uploaded_at: instant,
                 detected_type: Extracted<DocumentType>,
                 parse_status: "queued"|"parsing"|"parsed"|"failed",
                 parse_error: string|null, deleted_at: instant|null, claim_id: UUID|null }

DocumentType  "policy_schedule"|"policy_wording"|"discharge_summary"|"itemised_bill"|
              "payment_receipt"|"investigation_report"|"denial_letter"|"id_proof"|"unknown"

Policy        { id, insurer: {id, name, irdai_code|null}|null, policy_number|null,
                product_name|null, start_date|null, end_date|null,          // nullable, D-25
                policy_type: "individual"|"family_floater"|"group_employer"|"top_up"|"other",
                members: Member[], coverage_profile: CoverageProfile|null, source_document_id }

CoverageProfile { policy_id, sum_insured: Extracted<paise>, co_pay_percent: Extracted<number>,
                  sub_limits: SubLimit[], waiting_periods: WaitingPeriod[],
                  exclusions: Extracted<string>[], intimation_deadline_hours: Extracted<number>,
                  extraction_completeness: number 0..1 }

SubLimit      { category: "room_rent"|"icu"|"procedure"|"ambulance"|"opd"|"other", label,
                cap_amount: Extracted<paise>,
                cap_basis: "per_day"|"per_claim"|"per_policy_year"|"percent_of_sum_insured"|"other",
                percent_value: number|null }

WaitingPeriod { kind: "initial"|"disease_specific"|"pre_existing"|"maternity"|"other",
                months: Extracted<number>, applies_to|null, starts_on|null, expires_on|null }

Member        { id, full_name, relationship: string, date_of_birth: date|null }
```

Claim shapes are in §4. Exact Pydantic definitions: `apps/api/app/schemas/` and
`contracts/models.py`.

#### Behaviour worth knowing

- **Upload → policy.** A `POST /documents` with no `claim_id` is a policy document.
  The parse job itself creates the `Policy`. When the job succeeds,
  `result.policy_id` is the new policy's id (it can be `null` if nothing could be
  extracted). There is no separate "create policy" call.
- **Upload → claim document.** With a `claim_id` you own, the file is *classified*,
  not parsed (D-34). `job.kind` is still `parse_document`, `result.policy_id` is `null`.
- **Accepted file types:** `application/pdf`, `image/png`, `image/jpeg` only, checked by
  the file's leading bytes (D-29). PNG/JPEG *policy* uploads are stored, but their job
  fails with a message asking for a PDF. PNG/JPEG *claim* documents are classified
  normally.
- **Job progress steps** (`progress.step`, `percent` is a fixed marker):
  policy parse `uploading 5` → `parsing_layout 20` → `extracting_fields 80` →
  `storing 90` → `done 100`. Claim-document classification `uploading 5` →
  `classifying 40` → `storing 90` → `done 100`.
  A real parse takes from 20 s to several minutes and is killed after 300 s.
- **Polling** (D-07): every 1 s for the first 10 s, then every 3 s; give up at 180 s
  with a "still working, check back" state. Finished jobs are kept 24 h.
- **Idempotency** (D-13, D-27): a repeat of the same key with the same file returns the
  original `202` body and creates nothing. Generate one key per user-initiated upload
  (a UUID is fine) and reuse it on retries of that upload.
- **A document before it's read:** `page_count` is `0` and `detected_type` is
  `{ value: null, confidence: "low", provenance: null, user_confirmed: false }`.
  A parsed *policy* document keeps `detected_type.value = null`; only claim documents
  get a type.
- **`PATCH /documents/{id}`** sets `value` and `user_confirmed: true`; `confidence` and
  `provenance` stay as the classifier left them.
- **Pagination:** `next_cursor` is the id of the last item on the page. Pass it back as
  `cursor`. `null` means last page. `total` counts all matching documents.
- **Field correction** (D-30): correctable `field_path`s are exactly `sum_insured`,
  `co_pay_percent`, `intimation_deadline_hours`, `sub_limits.<category>.cap_amount`,
  `waiting_periods.<kind>.months`. `user_confirmed` must be `true` and `value`
  non-null and of the field's type (integer paise for money). If the path matches
  several rows: `409 ambiguous_field_path`, nothing changed.

### 1b. In `CONTRACTS.md` but NOT implemented

Calling any of these on the real server today gives `404 not_found`, except
`POST /policies`, which gives `405 method_not_allowed`. The web app still serves them
from mocks; their mock responses are in `docs/android-fixtures/` (§7) if you want to
build the screens against fixtures.

| # | Method & path | Pipeline | Shape (types.ts) | Note |
| --- | --- | --- | --- | --- |
| 8 | `POST /policies` | policies/upload | `Policy` | Probably never needed: the parse job creates the policy (CONTRACTS §4 item 4). |
| 11 | `POST /policies/{id}/questions` | ask (Q&A) | `202 JobAccepted` → `Job<QuestionAnswerResult>` | Engine C not built. |
| 17 | `POST /claims/{id}/eligibility` | eligibility | `EligibilityAssessment` | Engine B not built. |
| 19 | `POST /claims/{id}/bill-validation` | bill validation | `BillValidationReport` | Engine B not built. |
| 20 | `POST /claims/{id}/grievance-drafts` | grievance | `202 JobAccepted` → `Job<GrievanceDraft>`; `Idempotency-Key` required | Engine C not built. |
| 21 | `GET /alerts` | alerts | `Alert[]` | |
| 22 | `GET /ombudsman-awards` | benchmarks / precedent | `Collection<OmbudsmanAward>` | |
| 23 | `GET /insurers/benchmarks` | benchmarks | `InsurerBenchmark[]` | |

---

## 2. Downloading a document's file

Two steps (D-26). Code: `get_document_file` in
`apps/api/app/api/v1/documents.py:289`, link signing in `apps/api/app/storage/local.py`.

**Step 1: ask for a link (needs the token).**

```http
GET /api/v1/documents/{document_id}/file
Authorization: Bearer <token>
```

```json
200 OK
Content-Type: application/json

{
  "url": "http://192.168.1.23:8000/api/v1/local-files?path=...&expires=1792000000&signature=3f9a...",
  "expires_at": "2026-10-14T10:05:00.123456Z"
}
```

Errors: `401`, `404` (unknown, deleted, or another household's document), `503`
`storage_unavailable` (`retryable: true`).

**Step 2: load `url` as given, with no `Authorization` header.**

- Treat `url` as opaque. Don't parse or rebuild it.
- It's valid for **5 minutes** (`SIGNED_URL_LIFETIME_SECONDS = 300`). If it has expired,
  or the server restarted (the signing key is regenerated on every start), the link
  returns `403 link_not_valid`; request a new one from step 1.
- The response is the raw file. `Content-Type` comes from the file extension
  (`application/pdf`, `image/png`, `image/jpeg`). It honours `Range` requests, so a PDF
  renderer can fetch pages piecemeal.
- With the default local storage, the host in `url` is **whatever host your request
  used** (`request.base_url`, `documents.py:317`). If the phone called
  `http://192.168.1.23:8000`, the link points there too, so it's reachable from the
  phone. If the server is switched to `STORAGE_BACKEND=supabase`, `url` is a Supabase
  signed HTTPS URL instead; the client code is the same.

---

## 3. Bounding boxes (`Provenance.bbox`)

```json
"provenance": {
  "document_id": "0192...",
  "page": 14,
  "bbox": [0.118, 0.402, 0.871, 0.437],
  "snippet": "...room rent shall not exceed Rs. 5,000 per day..."
}
```

(The bbox numbers above are illustrative. None of the mock fixtures carries a
non-null bbox.)

| Property | Value |
| --- | --- |
| Field order | `[x0, y0, x1, y1]`: left, top, right, bottom |
| Normalisation | Each coordinate is a fraction 0..1 of the page's width (x) or height (y). Multiply by the rendered page size in pixels. |
| Origin | **Top-left** corner of the page; y grows **downward** (D-23). Same as Android's `Canvas`, so no flip is needed. |
| Page | `page` is **1-indexed**. Android's `PdfRenderer.openPage()` is 0-indexed: use `page - 1`. |
| Nullability | `provenance` may be `null` (no evidence: render as unverified). `bbox` may be `null` while `page` and `snippet` are set (the page is known, the exact spot isn't). |

The same convention applies to `DocumentChunk.bbox`.

Code that produces it:

- `engines/document/geometry.py:27-61`, `normalise_bbox()`: converts Docling's boxes
  to `(x0, y0, x1, y1)`, top-left, 0..1. Docling uses a bottom-left origin for text and
  a top-left origin for table cells; lines 47-57 read each box's own `coord_origin` and
  flip bottom-left ones (`y0 = (page_height - t) / page_height`). Values marginally
  outside 0..1 are clamped (lines 64-81).
- `engines/document/provenance.py:392-400` builds `Provenance(page=match.page_no,
  bbox=normalise_bbox(...))`; `page_no` is Docling's page number, which starts at 1.
- `contracts/models.py:13` (`BoundingBox = tuple[float, float, float, float]`), `:35`
  (`page: int = Field(ge=1)`, so page 0 is rejected) and `:41` (every coordinate must
  be within 0..1).

---

## 4. Claims

### Endpoints

`GET /claims`, `POST /claims`, `GET /claims/{id}`, `POST /claims/{id}/events`,
`POST /claims/{id}/completeness`. See §1a for errors.

**Create:**

```json
POST /api/v1/claims
{
  "policy_id": "0192...",
  "member_id": "0192...",
  "claim_type": "reimbursement",          // cashless | reimbursement | other
  "admission_type": "planned",            // planned | emergency | other
  "hospital_name": "City Hospital",       // 1–200 chars after trimming
  "admitted_on": "2026-09-20",            // date or null
  "discharged_on": "2026-09-24",          // date or null, not before admitted_on
  "claimed_amount": 8500000               // integer paise or null
}
```

All eight keys are required, even when the value is `null`. The server writes the
first event (`null → intimated`) itself.

**Append an event (the only way to change state, D-16):**

```json
POST /api/v1/claims/{id}/events
{ "to_state": "denied", "occurred_at": "2026-08-10T11:00:00+05:30", "note": null }
```

- `note` key is required (may be `null`, max 2000 chars).
- `occurred_at` must carry a UTC offset (`422` otherwise) and must not be more than
  5 minutes in the future (`422`). It may be earlier than the previous event's.
- Returns the whole updated `Claim`.

### The `Claim` response

```text
Claim { id, policy_id, member_id, claim_type, admission_type, hospital_name,
        admitted_on|null, discharged_on|null, claimed_amount|null, settled_amount|null,
        current_state: ClaimState,
        events: ClaimEvent[],                 // oldest first (server sequence order)
        deadlines: Deadline[],
        omitted_deadlines: OmittedDeadline[] }

ClaimEvent { id, claim_id, from_state|null, to_state, occurred_at, note|null,
             source: "user"|"insurer_letter"|"system" }

Deadline { id, label, due_at, days_remaining: int, basis: string,
           urgency: "normal"|"soon"|"critical"|"expired",
           source: { document, section|null, url|null } | null,
           verified: bool }

OmittedDeadline { id, label, reason }
```

- `deadlines` are computed on every read (D-17). `due_at` is end of day in India
  (`23:59:59+05:30`). Count down from `due_at`, never from your own arithmetic.
- **Every deadline rule is currently `verified: false`** (rules in
  `apps/api/app/rules/deadline_rules.yaml`: `claim_intimation`, `insurer_decision`,
  `escalation_eligibility`, `ombudsman_filing`). The app **must** mark unverified
  deadlines visibly (D-33, product-integrity rule 6).
- `CompletenessReport` is
  `{ claim_id, required[], present[], missing[], advisory_note, required_details[], verified }`;
  also `verified: false` for now and must be shown as such (D-35).

### States

From `apps/api/app/claims/state_machine.py:21-33`, the only definition in the code
(`TRANSITIONS` dict; ratified as D-31):

`intimated`, `documents_submitted`, `under_review`, `queried`, `approved`, `denied`,
`escalated`, `resolved`. A new claim starts in `intimated` (`INITIAL_STATE`).

Add `unknown` to your Kotlin enum as a parse fallback only (types.ts does the same);
it is never sent by the server and never a valid target.

### Allowed transitions

| From | Allowed `to_state` |
| --- | --- |
| `intimated` | `documents_submitted`, `queried` |
| `documents_submitted` | `under_review`, `queried` |
| `under_review` | `queried`, `approved`, `denied` |
| `queried` | `documents_submitted`, `under_review` |
| `approved` | `resolved` |
| `denied` | `escalated`, `resolved` |
| `escalated` | `resolved` |
| `resolved` | none (closed) |

### 409 responses on `POST /claims/{id}/events`

**Illegal transition**, including an unknown `to_state` (`apps/api/app/claims/events.py:136-144`).
One `field_errors` entry per allowed target, in the order of the table above. Rebuild
the user's choices from these without another request. A closed claim returns an
empty list.

```json
409 Conflict
{
  "error": {
    "code": "illegal_transition",
    "message": "That transition isn't allowed from the claim's current state.",
    "field_errors": [
      { "field": "to_state", "message": "escalated" },
      { "field": "to_state", "message": "resolved" }
    ],
    "request_id": "01a1...",
    "retryable": false
  }
}
```

**Lost a race** (D-32, `events.py:176-181`): two requests changed the same claim at
once and this one lost. Reload the claim and let the user decide again.

```json
409 Conflict
{
  "error": {
    "code": "claim_changed",
    "message": "This claim was updated at the same moment by another request. Reload it and try again.",
    "field_errors": [],
    "request_id": "01a1...",
    "retryable": true
  }
}
```

(`claim_has_no_history` is also a 409 but can only happen if the database was edited by
hand.)

---

## 5. Running the backend so a phone can reach it

The demo runs on Ayush's Mac; there is no cloud deployment.

**Start it** (from the repo root):

```bash
cd apps/api
../../.venv/bin/python -m app
```

This runs uvicorn on `HOST:PORT` from `apps/api/.env`. The defaults are
**`HOST=0.0.0.0`** (listen on every network interface, so other devices on the Wi-Fi
can connect) and **`PORT=8000`** (`apps/api/app/core/config.py:41-42`,
`apps/api/app/__main__.py`). The current `.env` doesn't override either. If macOS asks
whether Python may accept incoming connections, click **Allow**.

First time only, seed the dev household the stub token maps to:

```bash
cd apps/api && ../../.venv/bin/python scripts/seed.py     # idempotent
```

**Find the Mac's IP** (Wi-Fi is usually `en0`):

```bash
ipconfig getifaddr en0
```

If that prints nothing, try `ipconfig getifaddr en1`, or look in System Settings →
Wi-Fi → Details → TCP/IP.

**Test from the phone's browser** (phone on the same Wi-Fi, no token needed):

```
http://<Mac IP>:8000/api/v1/health
```

Expected body: `{"status":"ok"}`. If it times out, check the macOS firewall and that
both devices are on the same network. Some campus and guest Wi-Fi networks isolate
clients from each other.

**Android app settings:**

- Base URL `http://<Mac IP>:8000`; append `/api/v1` to it.
- It's plain `http://`, which Android blocks by default. In the **debug** build, set
  `android:usesCleartextTraffic="true"` or add a network security config that permits
  the Mac's IP.
- CORS does not apply to a native app; nothing needs changing on the server.
- The Mac's IP can change between sessions. Make the base URL configurable in a debug
  settings screen.
- The emulator reaches the Mac at `http://10.0.2.2:8000` instead.

---

## 6. The dev stub token

The API accepts one fixed stub token as a stand-in for a real Supabase sign-in, **only
while the server runs with `ENVIRONMENT=dev`** (`apps/api/app/core/auth.py:106`; the
current `.env` is `dev`). It maps to the household created by `scripts/seed.py`.

Header format:

```http
Authorization: Bearer <stub token>
```

That is the word `Bearer`, one space, then the token, with no quotes. The value isn't
copied here: it is the `STUB_TOKEN` constant in `apps/api/app/core/auth.py`, the same
value the web client sends. Ask Ayush, and keep it in a debug-only build config field,
not in source.

- Missing or malformed header → `401 unauthorized`.
- Stub token on a server with `ENVIRONMENT` other than `dev` → `401` (it's then checked
  as a real JWT and fails).
- Stub token accepted but the DB isn't seeded → `403 no_household`.
- Real sign-in later: a Supabase Auth access token (ES256 JWT) in the same header. No
  client change other than where the token comes from.
- While the server runs in dev, anyone on the same Wi-Fi who has the stub token can read
  the seeded household. Use a network you trust.

---

## 7. Mock fixtures: `docs/android-fixtures/`

These are the responses the **web app's MSW mocks** return (`apps/web/mocks/`). They
were produced by running those handlers unchanged in Node and saving each response
body. Each file is the raw response body; the status is in the table and in
`_index.json`. Regenerating them gives new generated ids and timestamps but the same
shapes.

Use them for Android UI work and as test fixtures, with these caveats (details in §9):

- Ids are readable strings (`claim-denied-ped`), not UUIDs. Real responses use UUIDv7.
- Mock job `progress.step` names differ from the real server's (§1a).
- The mock document-file `url` is a relative path (`/kitchen-sink/sample-policy.pdf`); the
  real one is absolute.
- The mock's Ombudsman deadline uses a 30-day placeholder; the real server uses its
  rules file, and its `due_at` is end of day IST.
- No fixture contains a non-null `bbox`.

| File | Request | Status | Implemented on the real server? |
| --- | --- | --- | --- |
| `get-health.json` | `GET /health` | 200 | Yes |
| `get-members.json` | `GET /members` | 200 | Yes |
| `get-policies.json` | `GET /policies` | 200 | Yes |
| `get-policies-id.json` | `GET /policies/{id}` | 200 | Yes |
| `patch-policies-id-coverage-profile-fields-field_path.json` | `PATCH /policies/{id}/coverage-profile/fields/sub_limits.room_rent.cap_amount` | 200 | Yes |
| `post-policies.json` | `POST /policies` | 200 | **No** |
| `post-documents.202.json` | `POST /documents` (policy upload) | 202 | Yes |
| `post-documents.422-missing-idempotency-key.json` | `POST /documents` without the header | 422 | Yes |
| `get-jobs-id.running.json` | `GET /jobs/{id}` right after upload | 200 | Yes |
| `get-jobs-id.parse_document-succeeded.json` | `GET /jobs/{id}` after the parse | 200 | Yes |
| `get-documents.json` | `GET /documents?limit=20` | 200 | Yes |
| `get-documents-claim_id.json` | `GET /documents?claim_id={id}` | 200 | Yes |
| `get-documents-id.json` | `GET /documents/{id}` | 200 | Yes |
| `patch-documents-id.json` | `PATCH /documents/{id}` | 200 | Yes |
| `get-documents-id-file.json` | `GET /documents/{id}/file` | 200 | Yes |
| `get-claims.json` | `GET /claims` | 200 | Yes |
| `get-claims-id.json` | `GET /claims/{id}` (denied claim) | 200 | Yes |
| `post-claims.201.json` | `POST /claims` | 201 | Yes |
| `post-claims-id-events.json` | `POST /claims/{id}/events` | 200 | Yes |
| `post-claims-id-events.409-illegal-transition.json` | `POST /claims/{id}/events`, illegal move | 409 | Yes |
| `post-claims-id-completeness.json` | `POST /claims/{id}/completeness` | 200 | Yes |
| `post-claims-id-eligibility.json` | `POST /claims/{id}/eligibility` | 200 | **No** |
| `post-claims-id-bill-validation.json` | `POST /claims/{id}/bill-validation` | 200 | **No** |
| `post-claims-id-bill-validation.409-bill-not-parsed.json` | same, no bill | 409 | **No** |
| `post-policies-id-questions.202.json` | `POST /policies/{id}/questions` | 202 | **No** |
| `get-jobs-id.answer_question-succeeded.json` | `GET /jobs/{id}` (Q&A result) | 200 | **No** (job kind) |
| `post-claims-id-grievance-drafts.202.json` | `POST /claims/{id}/grievance-drafts` | 202 | **No** |
| `get-jobs-id.generate_grievance_draft-succeeded.json` | `GET /jobs/{id}` (grievance result) | 200 | **No** (job kind) |
| `get-alerts.json` | `GET /alerts` | 200 | **No** |
| `get-ombudsman-awards.json` | `GET /ombudsman-awards?limit=20` | 200 | **No** |
| `get-insurers-benchmarks.json` | `GET /insurers/benchmarks` | 200 | **No** |
| `error-401-missing-token.json` | any route, no token | 401 | Yes |
| `error-404-not-found.json` | `GET /policies/{unknown id}` | 404 | Yes |
| `_index.json` | Machine-readable list of the above | — | — |

---

## 8. Product rules the Android UI must follow

These come from `CLAUDE.md` and apply to both clients:

1. Every extracted value shows where it came from (tap → page + highlight). If
   `provenance` is `null`, show the value as **unverified**, never as confirmed.
2. No bare percentages, gauges or speedometers for eligibility; always show the checks.
3. "Insufficient information" is a normal informational state, not an error. Name the
   missing fact and the document that would resolve it.
4. Unverified deadlines and checklists (`verified: false`) are visibly marked.
5. Wording says "assessment", "estimate", "based on your documents". Never promise an
   outcome or give legal advice.

---

## 9. Where `CONTRACTS.md` doesn't match the implemented behaviour

These are listed, not fixed. `CONTRACTS.md` and the web mocks were left unchanged.
Each needs Ayush to decide whether the doc or the code moves.

### `CONTRACTS.md` vs the backend

1. **Eight endpoints in the table are not implemented** (rows 8, 11, 17, 19–23; §1b).
   `CONTRACTS.md` doesn't mark which rows are live. §1 also says "exactly three
   endpoints are long-running jobs", but only `POST /documents` exists today.
2. **`GET /local-files` is not listed.** It's a real, public (no bearer) route
   (`apps/api/app/api/v1/local_files.py`), described only in D-26. D-24 says "every
   other route requires the bearer token", which this route contradicts on purpose.
   D-24's wording could name it as an exception.
3. **§3 says `PATCH /documents/{id}` "bumps `confidence` to `high`".** The backend
   leaves `confidence` unchanged (`apply_correction` in
   `apps/api/app/services/extracted_columns.py:37`), as D-34 requires. §3 is stale.
4. **§3 says the claim state graph is "a mock-only assumption, not a ratified rule".**
   It was ratified as D-31 and lives in `apps/api/app/claims/state_machine.py`. (§4
   item 6 is marked resolved, but the §3 paragraph wasn't updated.)
5. **§3 describes deadlines as one rule** (Ombudsman window from a placeholder constant
   in the mock). The backend computes four rules from `deadline_rules.yaml`, uses 1 year
   for the Ombudsman window (unverified), sets `due_at` to `23:59:59+05:30`, and fills
   `omitted_deadlines`.
6. **§3 says idempotency replay is "byte-for-byte" for any repeat key.** The backend
   replays only when the file's SHA-256 matches; a different file under the same key is
   `409 idempotency_key_reused` (D-27). Row 2 lists that 409, so only the §3 paragraph
   is stale.
7. **Errors the backend emits that the table omits:** `403 no_household` (valid token,
   no household), `503 auth_unavailable` and `503 storage_unavailable`
   (`retryable: true`), `405 method_not_allowed` on an unimplemented method of a known
   path, and on row 2, `422` for an unknown `claim_id` or for file contents that don't
   match the declared type.
8. **Row 14 (`POST /claims`)** lists only `422` generally. The backend also rejects an
   unknown `member_id` (the mock checks only `policy_id`) and `discharged_on` before
   `admitted_on`.
9. **Request bodies need every key.** The backend treats nullable request fields as
   required keys (`note` on events; `admitted_on`, `discharged_on`, `claimed_amount` on
   claim creation). Neither `CONTRACTS.md` nor the decisions doc says so; D-05 covers
   only responses.
10. **§1's hybrid-mode allowlist** lists three routes; `apps/web/src/api/hybridRoutes.ts`
    now has five (adds `GET /documents/{id}/file` and the field-correction `PATCH`).
    This is a frontend note, but it is stale.
11. **Job progress step names aren't in `CONTRACTS.md`.** D-28 and D-34 define them
    (`uploading`, `parsing_layout`, …); the mock uses different names
    (`classifying_pages`, `extracting_tables`, `structuring_coverage_profile`).

### The web mocks vs the backend

Not `CONTRACTS.md` itself, but `CONTRACTS.md` §1 calls the handlers "the executable
spec", so these matter to anyone building from the fixtures:

12. `GET /health`: the mock requires a bearer token; the backend doesn't (D-24).
13. Upload types: the mock also accepts `image/heic` and `image/webp`; the backend
    accepts only PDF, PNG and JPEG (D-29).
14. `Extracted.confidence`: types.ts and the mock use `"unknown"` (a fresh upload's
    `detected_type`); the backend only ever sends `high | medium | low` and uses `"low"`
    with `value: null` before classification. Keep `unknown` in the Kotlin enum as the
    escape hatch anyway.
15. A parsed policy document: the mock labels it `policy_schedule` with `high`
    confidence; the backend leaves `detected_type.value` `null`. The mock also sets an
    estimated `page_count` before parsing; the backend reports `0` until parsed.
16. Document file `url`: the mock returns a relative path; the backend returns an absolute
    URL.
17. Pagination cursors: the mock's `next_cursor` is a numeric offset; the backend's is the
    last item's id. Both are opaque to clients, so this only matters if someone parses
    it.
