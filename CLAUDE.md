# Project instructions

Unravel: a health-insurance policy-and-claim assistant for Indian policyholders. Capstone project.
Monorepo, trunk-based. The frontend (`apps/web`) was built first on MSW mocks as the integration harness; the FastAPI backend (`apps/api`) is now being built to satisfy it.

Read before starting work in these areas:

- Ratified API contract decisions (BINDING): @docs/API_DECISIONS.md
- Endpoint specification (BINDING): `CONTRACTS.md` at the repo root
- Frontend build plan, screen specs, and the domain types in §5: `docs/claude-code-frontend-prompt.md`
- Engine A findings: `engines/document/SPIKE_NOTES.md`

## Architecture

Four engines compose nine features.

- Engine A, document understanding: `engines/document/`. Finished. Public API is `parse_and_extract(file_path, document_kind) -> ExtractionResult`.
- Engine B, deterministic rules and eligibility: not built yet.
- Engine C, hybrid retrieval and citation-verified generation: not built yet.
- Engine D, data layer (multi-insurer schema, claim state machine): `apps/api/`.

## The two governing rules

Every design choice answers to these.

1. **No fact without provenance.** Every value extracted from a user's document carries page + normalised bbox. A number without provenance is worse than no number.
2. **No verdict without reasoning.** Deterministic code decides anything a user might act on financially. The LLM does perception and language only, always schema- or citation-bound.

## Binding contract rules

Violating any one of these breaks a client. There are **two** clients of this API: the web app and an Android app.

- All routes live under `/api/v1`.
- JSON is `snake_case` in both directions. No camelCase aliases, no casing transform.
- Money is **integer paise** on the wire and in the database (`BIGINT`). Never float or Decimal on the wire.
- Nulls are always emitted, never omitted. Never use `exclude_none`.
- Every extracted field is `Extracted[T]` = `{value, confidence: high|medium|low, provenance, user_confirmed}`. Never flatten it.
- Every non-2xx response, including FastAPI validation errors and 404s, returns exactly
  `{"error": {"code", "message", "field_errors": [{"field", "message"}], "request_id", "retryable"}}`.
  FastAPI's default `{"detail": ...}` must never reach a client.
- Ownership comes from the JWT. No endpoint accepts `household_id`. Another household's resource returns 404, not 403.
- `POST /documents` returns 202 + `job_id`. Clients poll `GET /jobs/{id}`.
- Ids are UUIDv7, server-generated. Instants are `timestamptz` in UTC, serialised ISO-8601 with offset. Calendar values are `DATE`.
- Every string enum has an escape-hatch member (`"unknown"` or `"other"`; check `packages/contracts-ts/src/types.ts` for which).
- `Provenance.bbox` is `[x0, y0, x1, y1]`, normalised 0..1, top-left origin; pages are 1-indexed (D-23).
- `GET /health` is public; every other route requires `Authorization: Bearer` (D-24).

**Changing the contract:** stop and ask. Contract changes need Ayush's explicit approval and must be recorded in `docs/API_DECISIONS.md` in the same change. Do not invent endpoints or response shapes beyond `CONTRACTS.md`. If something in `API_DECISIONS.md` or `CONTRACTS.md` looks wrong, stop and say so; never deviate silently.

## Directory ownership

| Path | Owner | Rule |
| --- | --- | --- |
| `apps/web/` | Frontend | **Backend work does not edit it.** It is the harness the backend must satisfy. |
| `packages/contracts-ts/` | Frontend | Hand-written TS types, authoritative until OpenAPI generation replaces them (D-21). |
| `apps/api/` | Backend | FastAPI app, Alembic chain, tests. |
| `contracts/` | Shared | Pydantic models imported by Engine A and the API. Fix in place; never rewrite. |
| `engines/document/` | Engine A | Do not change its behaviour. Its tests must stay green with an unchanged count. |

## Product-integrity rules

These are not style preferences. Breaking one makes the product dishonest, which is the failure this project cannot afford.

1. No fact extracted from a user's document renders without a provenance affordance. Missing provenance renders as unverified, never as confirmed.
2. No eligibility verdict without its underlying checks. **No bare percentages, gauges, or speedometers anywhere.**
3. Abstention ("insufficient information") is a normal state, styled as information, not as an error. Always name the missing fact and the document that resolves it.
4. Generated grievance paragraphs with `verified: false` render visibly flagged. Never silently.
5. Copy never implies a guaranteed outcome and never gives legal advice. Say "assessment", "estimate", "based on your documents".
6. Never invent regulatory figures, deadlines, or IRDAI/Ombudsman numbers. Use a placeholder and log it under "Needs verification" in `DECISIONS.md`.

## Backend conventions

Stack is fixed: Python 3.12, FastAPI, SQLAlchemy 2.0 async, Alembic (one linear chain), Pydantic v2, pydantic-settings, PostgreSQL on Supabase (pgvector enabled, unused for now), uvicorn. FastAPI `BackgroundTasks` for jobs: no Celery, no broker. venv + `requirements.txt`. No Docker. Do not add libraries without asking.

- Ayush must be able to explain every line to a university panel. Prefer clear code over clever code, and explain design decisions as you go.
- Treat anything from the former `feat/be-foundations` branch as untrusted. Do not build on it.
- Routes raise `ApiError`; they never return an error body by hand and never raise a bare `HTTPException` with a dict detail. All error responses are built in `apps/api/app/core/errors.py`.
- API response models inherit `ApiModel` (`apps/api/app/schemas/base.py`).
- New ids come from `new_id()` in `apps/api/app/core/ids.py`. Never `uuid4()`.
- Each `Extracted[T]` field is stored as five columns: `_value`, `_confidence`, `_provenance` (JSONB), `_original_value`, `_user_confirmed`. `_original_value` is written once and never updated: the parser's answer must survive user corrections, because that comparison is the extraction-accuracy evaluation data.
- Engine A fills placeholder UUIDs. They are replaced by `remap_ids()` in `apps/api/app/services/extraction_mapper.py` before anything is stored. No placeholder may reach the database.
- Login tokens are Supabase JWTs signed with ES256. `apps/api/app/core/auth.py` verifies them against the project's public keys (JWKS, derived from `SUPABASE_URL`); the API holds no signing secret. The stub token `mock-household-token` is accepted only when `ENVIRONMENT=dev`.
- Protected routes depend on `get_current_household` and scope every query to `household.household_id`.
- Alembic lives in `apps/api/alembic`; run it from `apps/api`. After changing a model, `alembic check` must report no differences.
- Secrets live in `apps/api/.env`, which is gitignored. Never commit `.env` or keys. `.env.example` is committed.
- Two virtualenvs: the root `.venv` runs the API; `engines/document/.venv` runs Engine A's tests. The root `pyproject.toml` installs `contracts` with `pip install -e .`; keep that working.

### Verification before calling backend work done

Run these and show the actual output:

- `cd engines/document && .venv/bin/python -m pytest` (84 passed; the count must not change)
- `cd apps/api && ../../.venv/bin/python -m pytest`
- `cd apps/api && ../../.venv/bin/python -m alembic upgrade head`, then `downgrade -1`, then `upgrade head`, then `check`
- `curl /api/v1/health` returns `{"status":"ok"}`
- `curl /api/v1/nonexistent` returns the error envelope, not `{"detail": ...}`
- A request with no `Authorization` header to a protected route returns the 401 envelope
- `python -c "from contracts.models import Extracted, CoverageProfile, SubLimit; print('ok')"` (from the repo root)
- `git status`: `.env` must not appear

Every phase needs tests for what it adds. Standing ones: error envelope for 404/422/500; a model with a `None` field serialises the key as `null`; money fields are `int`; auth rejects missing and invalid tokens; `remap_ids` never leaves a placeholder UUID.

### Backend commands

- `cd apps/api && ../../.venv/bin/python -m uvicorn app.main:app --reload`: dev server on port 8000
- `cd apps/api && ../../.venv/bin/python -m pytest`: API tests
- `cd apps/api && ../../.venv/bin/python scripts/seed.py`: seed the dev household (idempotent)
- `cd engines/document && .venv/bin/python -m pytest`: Engine A tests

## Frontend conventions

- TypeScript strict. No `any`. `tsc --noEmit` must pass before you report a phase complete.
- `fetch` is called in exactly one file: `src/api/client.ts`. Components call hooks in `src/api/endpoints/*`.
- Components never import from `mocks/`.
- Only `client.ts` reads `VITE_API_MODE` and `VITE_API_BASE_URL`.
- API JSON is `snake_case` in both directions. Do not transform casing.
- Money is integer paise. Rupee formatting exists only inside `<Money>`, using `Intl.NumberFormat('en-IN')`.
- Every screen implements five states: loading (skeletons, not spinners), empty, error with a working retry, degraded/low-confidence, abstained.
- Stack is fixed: React 18 + Vite, React Router v6, TanStack Query v5, Tailwind, shadcn/ui, lucide, Recharts, MSW, react-hook-form + zod, react-pdf, date-fns, Vitest. Do not add libraries outside this list without asking.

### Frontend commands

- `npm run dev`: Vite dev server with MSW
- `npm run build`: production build
- `npm run typecheck`: `tsc --noEmit`
- `npm run test`: Vitest
- `npm run generate:types`: regenerate TS types from the backend's OpenAPI (once the backend exists)

## Working agreement

- Work one phase at a time. Stop at each phase boundary, summarise what was built and what was verified (with real command output), list any decision needed, and wait.
- Branch per phase or workstream off the agreed base. Small commits, conventional messages. Never force-push.
- Ambiguity that does **not** affect the API contract: choose the conservative option, proceed, log it in `DECISIONS.md` (what was ambiguous, what you chose, what would change if reversed).
- Ambiguity that **does** affect the API contract: stop and ask.
- Frontend phases do not scaffold backend code, migrations, or Docker files. Backend work does not touch `apps/web/`.
