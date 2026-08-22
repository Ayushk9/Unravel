# Decisions log

Ambiguities encountered during the build, what was chosen, and what would change if
reversed. Per CLAUDE.md: contract-affecting ambiguity is asked about, not decided
here. Everything below is either a conservative call on a non-contract ambiguity, or
a contract-affecting one that was raised and resolved with the user before proceeding.

---

## Phase 0

### Repo layout: monorepo (`apps/web` + `packages/contracts-ts`) — asked, resolved

**Ambiguity:** `docs/claude-code-frontend-prompt.md` §5 says types live at
`src/api/types.ts` in a flat frontend repo. `docs/API_DECISIONS.md` D-21 (ratified)
says the hand-written authoritative types live at `packages/contracts-ts/types.ts`,
replaced by generated types once the backend ships. These directly conflict on repo
shape, and D-21 is scoped as binding on everything crossing the API boundary — this
affects what three backend developers will build against, so it was raised rather
than decided unilaterally.

**Resolution:** user chose the monorepo option. Root `package.json` uses npm
workspaces (`apps/*`, `packages/*`). `packages/contracts-ts` holds the hand-written
domain types now (`src/types.ts`, exported via `@internal/contracts-ts`);
`apps/web/src/api/types.ts` re-exports them so app code still imports from
`@/api/types` per convention. `apps/web` is the Vite frontend described in the brief.

**What would change if reversed:** collapse `packages/contracts-ts` into
`apps/web/src/api/types.ts` directly and drop the workspace split — a mechanical
move, no import-path changes needed outside `src/api/types.ts` itself since
components already import from `@/api/types`, not from the package directly.

### `FRONTEND_BRIEF.md` does not exist under that name

CLAUDE.md references `docs/FRONTEND_BRIEF.md`. The only brief present is
`docs/claude-code-frontend-prompt.md`, which appears to be the same document (product
context, screens, phases, working agreement all match). Treated it as the intended
file. **Needs verification against the user:** either rename the file to match
CLAUDE.md, or update CLAUDE.md's reference — currently the pointer and the target
disagree, which will confuse anyone who opens CLAUDE.md and follows the `@` link.

### React 18, not the scaffolded 19

`npm create vite@latest -- --template react-ts` scaffolds React 19 by default now.
CLAUDE.md pins the stack to React 18 explicitly. Pinned `react`/`react-dom`/
`@types/react`/`@types/react-dom` to `^18.3.x` in `apps/web/package.json` before
installing.

### TypeScript strictness beyond the template default

The scaffolded `tsconfig.app.json` did not set `"strict": true` — it only had a few
individual lint-flavoured flags (`noUnusedLocals`, etc.). Added `"strict": true`,
`"noUncheckedIndexedAccess": true`, `"noImplicitReturns": true` explicitly, since
CLAUDE.md requires strict mode and zero `any`.

### shadcn CLI and the monorepo path alias

`npx shadcn init` reads path aliases from the **root** `tsconfig.json`
(`compilerOptions.paths`), not from `tsconfig.app.json` even though the latter is
where Vite/tsc actually resolve `@/*` for the app. With only `tsconfig.app.json`
carrying the alias, the CLI silently failed alias resolution and wrote generated
files to a literal directory named `@` at the workspace root instead of `src/`.
Fixed by adding the same `paths` entry to `tsconfig.json`. Moved the two
misplaced files (`components/ui/button.tsx`, `lib/utils.ts`) into `src/` and
deleted the stray `@/` directory. Worth knowing before running `shadcn add` again
in this repo.

### shadcn init pulled in an unwanted default theme — reverted

The `nova` preset (chosen because it's Lucide/Radix-based, matching the stack)
seeded `index.css` with the generic oklch greyscale palette, a Geist font import,
a broken `@import "shadcn/tailwind.css"` (that package isn't meant to be a runtime
dependency — it's the CLI), and unused dark-mode/chart/sidebar tokens. All of this
would have shipped exactly the "shadcn out-of-the-box slate-and-blue" look the brief
explicitly rules out. Removed the `shadcn` and `@fontsource-variable/geist` packages
from `dependencies`, and rewrote `index.css`'s CSS variables to map onto the
`DESIGN.md` token set instead. Dropped the dark-mode variant and the chart/sidebar
tokens entirely for now — nothing in Phase 0 uses them, and CLAUDE.md says not to
build for hypothetical future needs. Re-add chart tokens in Phase 6 (benchmarking
charts) and sidebar tokens in Phase 1 if the nav ends up using that primitive.

### `mocks/` lives beside `src/`, not inside it

The brief's directory tree (§4) shows `src/api/` and `mocks/` as siblings. Read that
literally: `apps/web/mocks/` (not `apps/web/src/mocks/`). Component code never
imports from it either way, so this is a low-stakes placement call.

### Placeholder product name "PolicyClear"

Neither brief names the product. Used "PolicyClear" as a placeholder in the page
`<title>` and the Phase-0 shell heading purely so the shell isn't titled "web" (the
Vite default). Trivial to rename — appears in `index.html` and `App.tsx` only.

### `GET /api/v1/health` is not a ratified endpoint

Phase 0's own "done when" bar requires proving MSW intercepts a real call. None of
the vertical-slice endpoints in `API_DECISIONS.md` §7 exist yet (they arrive in
Phase 2 alongside fixtures and `CONTRACTS.md`), so a minimal `/health` handler was
added purely as an infra smoke test — it asserts the auth header is present (D-09)
and returns `{ "status": "ok" }`. Not part of any feature slice; can be dropped or
kept as a real backend health-check once Slice 1 exists.
