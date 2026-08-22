# Project instructions

Health-insurance policy-and-claim assistant for Indian policyholders. Capstone project.
Monorepo, trunk-based. Frontend is being built first as the integration harness for a FastAPI backend that does not exist yet.

Full briefs — read before starting work in these areas:

- Frontend build plan and screen specs: @docs/FRONTEND_BRIEF.md
- Ratified API contract decisions: @docs/API_DECISIONS.md

## Product-integrity rules

These are not style preferences. Breaking one makes the UI dishonest, which is the failure this project cannot afford.

1. No fact extracted from a user's document renders without a provenance affordance. Missing provenance renders as unverified — never as confirmed.
2. No eligibility verdict without its underlying checks. **No bare percentages, gauges, or speedometers anywhere.**
3. Abstention ("insufficient information") is a normal state, styled as information, not as an error. Always name the missing fact and the document that resolves it.
4. Generated grievance paragraphs with `verified: false` render visibly flagged. Never silently.
5. Copy never implies a guaranteed outcome and never gives legal advice. Say "assessment", "estimate", "based on your documents".
6. Never invent regulatory figures, deadlines, or IRDAI/Ombudsman numbers. Use a placeholder and log it under "Needs verification" in `DECISIONS.md`.

## Frontend conventions

- TypeScript strict. No `any`. `tsc --noEmit` must pass before you report a phase complete.
- `fetch` is called in exactly one file: `src/api/client.ts`. Components call hooks in `src/api/endpoints/*`.
- Components never import from `mocks/`.
- Only `client.ts` reads `VITE_API_MODE` and `VITE_API_BASE_URL`.
- API JSON is `snake_case` in both directions — do not transform casing.
- Money is integer paise. Rupee formatting exists only inside `<Money>`, using `Intl.NumberFormat('en-IN')`.
- Every screen implements five states: loading (skeletons, not spinners), empty, error with a working retry, degraded/low-confidence, abstained.
- Stack is fixed: React 18 + Vite, React Router v6, TanStack Query v5, Tailwind, shadcn/ui, lucide, Recharts, MSW, react-hook-form + zod, react-pdf, date-fns, Vitest. Do not add libraries outside this list without asking.

## Working agreement

- Work one phase at a time (phases are in `docs/FRONTEND_BRIEF.md`). Stop at each phase boundary, summarise, and wait.
- Branch per phase off `main`. Small commits, conventional messages. Never force-push.
- Ambiguity that does **not** affect the API contract: choose the conservative option, proceed, log it in `DECISIONS.md` (what was ambiguous, what you chose, what would change if reversed).
- Ambiguity that **does** affect the API contract: stop and ask. Three developers will build against it.
- Do not scaffold backend code, migrations, or Docker files in the frontend phases.

## Commands

- `npm run dev` — Vite dev server with MSW
- `npm run build` — production build
- `npm run typecheck` — `tsc --noEmit`
- `npm run test` — Vitest
- `npm run generate:types` — regenerate TS types from the backend's OpenAPI (once the backend exists)
