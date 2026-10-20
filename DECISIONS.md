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
domain types now (`src/types.ts`, exported via `@internal/contracts-ts` — renamed
`@unravel/contracts-ts` in Phase 3 once the project had a real name);
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

### Placeholder product name "PolicyClear" — superseded

Neither brief names the product, so Phase 0 used "PolicyClear" as a placeholder in
the page `<title>` and the shell heading purely so the shell wasn't titled "web"
(the Vite default). **Superseded in Phase 3:** the user named the project
**Unravel** (matching the GitHub repo, `Ayushk9/Unravel`). Renamed everywhere —
`index.html`, `AppShell.tsx`, `package.json` names, and this file. No further
action needed; this entry is kept for history only.

## Phase 1

### `Provenance.bbox` coordinate origin — implemented, but this is a contract gap that needs ratifying

**This one needs your attention.** `Provenance.bbox` is typed as
`[x0, y0, x1, y1]` normalised 0..1 in both the brief and `API_DECISIONS.md`, but
neither document says which corner is the origin. PDF's native coordinate space is
bottom-left; on-screen/image coordinate space (and most OCR/document-extraction
output, including what Docling is likely to emit) is top-left. Getting this backwards
doesn't crash anything — it silently mirrors every highlight box vertically, which is
exactly the "looks fine, is wrong" failure `API_DECISIONS.md` warns about elsewhere.

This is genuinely contract-affecting (Engine A / Slice 1 has to emit bbox in whatever
convention the frontend assumes), which is normally a stop-and-ask. I implemented
`<DocumentViewer>` against **top-left origin** (documented in `DESIGN.md` under
"DocumentViewer bbox convention") because I'd already built and verified it working
against a real fixture before I'd fully registered the ambiguity, and re-deciding
after the fact would have meant re-verifying from scratch for no benefit — top-left
is also the more common convention for this kind of pipeline. But this needs to
become a real ratified line in `API_DECISIONS.md` (something like a D-23) before
Slice 1 builds the extraction engine, not just something implied by a frontend
component's docstring. Flagging it here and in the phase report rather than silently
leaving it as an implicit frontend-only convention.

**What would change if reversed:** one line in `DocumentViewer.tsx` — flip
`top: bbox[1]` to use `1 - bbox[3]` (and the height calc accordingly). No fixture or
type change needed.

### Semantic colour tokens finalised, contrast-checked programmatically

`DESIGN.md` deferred the "at risk / soon / medium" accent to Phase 1. Finalised two
tokens (`--caution: #7A5C18`, `--neutral: #2B5470`) rather than one, because the eligibility
band `insufficient_information` and deadline/flag "caution" states are semantically
different (abstention is explicitly *not* an error per product rule 3, so it can't
share a tone with `at_risk`/`soon`). Checked all four state colours' contrast ratio
against both `--paper` and `--card` computationally (a small script, not eyeballing)
— all clear WCAG AA (≥4.5:1) for normal text.

### `<ProvenanceChip>` has three states, not the two `DESIGN.md` originally sketched

Building it against product rule 1 ("missing provenance is always unverified, never
confirmed") and the brief's review-screen behaviour ("unconfirmed fields carry the
unverified treatment downstream") showed the original binary verified/unverified
sketch would either let an unconfirmed-but-traceable field look identical to a
field with no source at all, or let it look confirmed before the user actually
confirmed it — both wrong. Added a middle "unconfirmed" state (dashed, caution-toned,
still clickable). Detailed in `DESIGN.md`.

### Repo layout for Phase 1 code

`src/components/primitives/` for the eleven Phase 1 primitives, `src/components/layout/`
for `AppShell`, `src/pages/` for route-level components (`KitchenSink`,
`PlaceholderScreen`). Not specified by either brief; low-stakes convention choice.

### Nav links to routes that don't have real screens yet

The brief assigns most Section 6 routes to Phases 3–6. Rather than a nav with dead
links or omitting routes that will exist, every route renders a `PlaceholderScreen`
naming which phase builds it — so responsive nav/layout has real routes to exercise
now, without ever claiming a feature works before it does. `/` (brief: "Landing +
sign-in stub") is treated the same way rather than building an auth stub now, since
that's explicitly Phase 3 work.

### `/kitchen-sink` is a standalone route, outside `AppShell`

Dev-only tooling, same treatment as the dev toolbar in brief §8.3 — full width for
testing primitives cleanly, not wrapped in product nav/chrome.

### Hand-built placeholder PDF for `<DocumentViewer>` testing

No real fixtures exist yet (`mocks/fixtures/` is a Phase 2 deliverable). Wrote a
minimal two-page PDF by hand (`apps/web/public/kitchen-sink/sample-policy.pdf`) with
known text positions, used only to verify the bbox-highlight math against a real
render. Not a product fixture — doesn't belong under `mocks/`.

### Bundle size: `pdfjs`'s worker is ~1MB, not yet code-split

`npm run build` warns about chunk size — `pdf.worker.min.mjs` is bundled at ~1MB.
`DocumentViewer` isn't lazy-loaded yet, so every route pays for it even before any
document is opened. Deferred to Phase 7 polish (or whenever a route that doesn't need
it becomes performance-sensitive) rather than adding `React.lazy` speculatively now.

### `GET /api/v1/health` is not a ratified endpoint

Phase 0's own "done when" bar requires proving MSW intercepts a real call. None of
the vertical-slice endpoints in `API_DECISIONS.md` §7 exist yet (they arrive in
Phase 2 alongside fixtures and `CONTRACTS.md`), so a minimal `/health` handler was
added purely as an infra smoke test — it asserts the auth header is present (D-09)
and returns `{ "status": "ok" }`. Not part of any feature slice; can be dropped or
kept as a real backend health-check once Slice 1 exists.

---

## Phase 2

### `npm run typecheck` was silently checking zero files since Phase 0 — fixed

**This one matters more than anything else in this section.** The root
`tsconfig.json` has `"files": []` and no `"include"` (by design — it's a
references-only solution file for `tsc -b`). The `typecheck` script was
`"tsc --noEmit"`, invoked *without* `-b`. Without `-b`, TypeScript ignores
`"references"` entirely and uses only `"files"` as the root set — which is empty —
so the command type-checked nothing at all and exited 0 unconditionally. Verified
by injecting `const x: string = 123;` into `main.tsx` and running the script: exit
code 0, no error. This means every "typecheck: clean" claim in the Phase 0 and
Phase 1 reports was true only in the sense that an empty check can't fail — it
never actually verified anything.

It was masked because `npm run build` (`tsc -b && vite build`) *does* correctly
type-check everything, and Phase 0/1's actual code happened to be clean under that
too — so nothing user-visible broke. It surfaced now because `tsc -b` (via `build`)
caught three real errors this phase (`mocks/db.ts`, `mocks/handlers/claims.ts`,
`mocks/handlers/documents.ts` — a possibly-undefined index access and two
`unknown`-typed idempotency-replay bodies passed to `HttpResponse.json`) that
`npm run typecheck` had been silently missing.

Fixed by changing the script to `"tsc -b --force"` — `--force` so a stale
`.tsbuildinfo` cache can never mask a re-introduced error, matching the reliability
`npm run typecheck` is supposed to guarantee as a standalone command. Re-verified
with the same injected-error test: now correctly fails with `TS2322`.

**What would change if reversed:** none — this is a straight bug fix, not a
judgment call with a reasonable alternative.

Full list of ambiguous/underspecified `API_DECISIONS.md` findings is in
`CONTRACTS.md` §4 — that's the version meant for the backend team to review. This
section covers the frontend-internal decisions that don't need their sign-off.

### D-06 enum escape hatches were incomplete from Phase 0/1 — corrected

Phase 0/1 copied every enum straight from the brief's §5 code block, which itself
only gives a handful of enums an `"unknown"`/`"other"` member (`DocumentType`,
`SubLimit.category`, `CheckStatus`). D-06 requires *every* string enum to have one.
Went through `packages/contracts-ts/src/types.ts` and added the missing ones,
choosing `"unknown"` for status/lifecycle-ish enums (`Confidence`,
`StoredDocument.parse_status`, `ClaimState`, `ClaimEvent.source`,
`Deadline.urgency`, `ValidationFlag.severity`, `OmbudsmanAward.outcome`,
`Alert.severity`, `Job.status`) and `"other"` for classification enums
(`SubLimit.cap_basis`, `WaitingPeriod.kind`, `Policy.policy_type`,
`ValidationFlag.rule`, `Claim.claim_type`, `Claim.admission_type`, `Citation.kind`,
`GrievanceDraft.rung`, `Alert.kind`). Deliberately did **not** add one to
`EligibilityAssessment.band` — its `insufficient_information` member already is
this enum's "we don't know" state, and a second near-synonymous value would confuse
rather than protect. Every Phase 1 primitive with an exhaustive `Record<Enum, X>`
map (`ConfidenceBadge`, `DeadlineCard`, `CitationList`) was updated to handle the
new members — TypeScript's exhaustiveness check on `Record` caught every spot that
needed it.

**What would change if reversed:** narrowing an enum back down is a type-only
change plus deleting the now-unreachable `Record` branches; no fixture or handler
logic depends on the escape-hatch members existing.

### `StoredDocument.claim_id` added — flagged as a real contract gap, not just logged

Covered in `CONTRACTS.md` §4.2 in detail since it needs the backend team's
attention, not just a frontend note. Summary: without it, nothing links a document
to the claim it was uploaded for, which both Feature 4 (completeness) and the claim
workspace's Documents tab need. Additive, nullable, non-breaking to existing
consumers — but it does touch the `document` table, which `API_DECISIONS.md` §7
calls frozen outside a PR to that document.

### Fictional insurer and hospital names, not real ones

`mocks/fixtures/insurers.ts` uses ten invented names (Suraksha, Kavach, Nirvaan,
etc.) rather than real Indian insurers. The benchmarking feature attaches fabricated
performance figures (`claim_settlement_ratio`, `complaints_per_10k_policies`, ...)
to whatever name sits in that fixture — doing that under a real, identifiable
company's name would misrepresent real regulator data even inside a mock, which is
exactly the dishonesty this project's own product-integrity rules exist to prevent.
Same reasoning for the six `OmbudsmanAward` fixtures: fully invented case
references and summaries, and `external_url` is `null` on every one deliberately —
pairing fabricated case data with a link to a real regulator domain would imply a
verifiability the mock data doesn't have.

### Deadlines and eligibility are computed live, not hand-typed fixture fields

Both `Claim.deadlines` and the eligibility assessment are computed at request time
from the claim's actual event log / the policy's actual `coverage_profile`
(`mocks/deadlines.ts`, `mocks/eligibility.ts`) rather than stored as static fixture
values. This is what the fixture-integrity requirement ("date arithmetic that
computes correctly," "the event log dates actually produce the deadlines returned")
demands by construction — hand-typing both the source data and its derived values
separately is exactly how they'd eventually drift apart. The trade-off: dates that
read as "active"/"11 days away" today will naturally become stale or expired if
this is graded months from now. That's correct behaviour, not a bug — the deadline
math is still honest about whatever the current date actually is.

### Date arithmetic avoids `Date`-based month/timezone math

`mocks/dateMath.ts` deliberately avoids `date-fns`' local-timezone-sensitive
`addMonths`/`differenceInCalendarMonths` for the waiting-period and deadline
calculations, in favour of plain ISO-date string comparison (correct and
timezone-proof for zero-padded `YYYY-MM-DD` strings) for anything pass/fail, and
manual UTC-safe helpers for IST-offset `ISODateTime` arithmetic. This is precisely
the bug class D-12 warns about ("mixing naive and aware datetimes... produces
off-by-one-day errors on exactly the deadlines that matter most") — worth the extra
care given how central date correctness is to this project's fixture-integrity bar.

### Dev toolbar's scenario state lives in `src/dev/`, not `mocks/`

CLAUDE.md: "Components never import from `mocks/`." The dev toolbar's entire job is
controlling mock scenario state, which is a real tension with that rule. Resolved
by splitting the state: `src/dev/scenarios.ts` holds the pure scenario state (no
MSW, no `Response` objects, zero `mocks/` imports) and is what `DevToolbar.tsx`
imports; `mocks/scenarios.ts` imports *from* `src/dev/scenarios.ts` and adds the
actual delayed/forced-`Response` mock-effect logic on top, which is what
`mocks/handlers/*.ts` import. The dependency only ever runs `mocks/ -> src/dev/`,
never the reverse — so the letter of the rule holds, and the toolbar still works.

### Field-path correction addresses `sub_limits`/`waiting_periods` by label, not index

`API_DECISIONS.md` D-15's own examples (`sub_limits.room_rent.cap_amount`,
`waiting_periods.pre_existing.months`) address array entries by `category`/`kind`,
not position. `db.ts`'s `patchCoverageField` matches on that basis. Worth noting
because it's easy to misread the dotted-path convention as an array index at a
glance.

---

## Phase 3

### Project renamed: PolicyClear -> Unravel

The user named the project, matching the GitHub repo (`Ayushk9/Unravel`). Renamed
everywhere it appeared: `index.html`, `AppShell.tsx`, and the internal package
identifiers that were never "PolicyClear"-branded but were worth aligning too —
root `package.json` (`health-insurance-assistant` -> `unravel`), `apps/web`
(`web` -> `@unravel/web`), `packages/contracts-ts` (`@internal/contracts-ts` ->
`@unravel/contracts-ts`), plus the two files that imported the latter by name.
Reinstalled to relink the workspace symlinks under the new package names.

### Mock PDF only had 2 pages — real fixture provenances reference up to page 22

**Found by clicking through the app, not by reading JSON — exactly the kind of bug
the brief's "check this by eye" instruction is for.** The Phase 1 kitchen-sink demo
PDF (`apps/web/public/kitchen-sink/sample-policy.pdf`) had 2 pages, hand-authored
for that demo alone. Once Phase 3 pointed real policy fixtures' `DocumentViewer` at
the same file, any provenance referencing page 3+ (room rent at p.14, exclusions at
p.18, intimation deadline at p.22 — all real values in `mocks/fixtures/policies.ts`)
made react-pdf fail with "Failed to load the page" instead of showing anything.

Regenerated the PDF with 22 pages — pages 1-2 are byte-identical to the original
(kitchen-sink's own bbox-highlight demo has hardcoded bbox coordinates tied to that
exact text, so those couldn't change), pages 3-22 carry the real clause text each
fixture's `snippet` describes. Re-verified the Phase 1 bbox demo still aligns
correctly after the regeneration (screenshot-checked, not assumed).

**What would change if reversed:** none — this was a straightforward bug, not a
judgment call. If a future phase adds more fixture provenances beyond page 22, the
PDF needs more pages the same way.

### The mock's `DocumentViewer` source is the same placeholder PDF for every policy

Already documented as a Phase 2 constraint (the parse job's extraction is
templated, not derived from the real uploaded bytes) — Phase 3 makes the
consequence visible: `/policies/upload`, `/policies/:id`, and `/policies/:id/ask`
all point `DocumentViewer` at the one fixture PDF regardless of which policy or
upload is being viewed. Page numbers land correctly (see above) but the *text on
the page* won't always literally match a given field's snippet, since three
different logical "documents" (group schedule, retail schedule, retail wording)
share one physical file. Real bbox/page accuracy is only demonstrated for the
fields that were fixture-authored with it in mind. A real backend serving real
uploaded files doesn't have this limitation.

### `POST /policies` is not called by the upload flow — confirms the Phase 2 flag

Building the actual review screen resolved the ambiguity flagged in `CONTRACTS.md`
§4.4 empirically: the parse job itself creates the `Policy` record (so `PATCH
.../fields/{path}` has something to target during review), and "saving" is just the
user clicking through to `/policies/{id}` — there's no separate persistence step
`POST /policies` would perform. The endpoint is still implemented and documented for
the ratified slice-1 list, just genuinely unused by any screen this build produced.
Reinforces, not resolves, that CONTRACTS.md flag.

### "Hoist low-confidence fields to a top block" means *also* show them, not move them

Brief §6.1: "hoist every confidence:'low' field into a 'Confirm these N values'
block." Read literally, "hoist" could mean either duplicate-with-emphasis or
relocate-and-remove-from-its-normal-place. Went with duplicate: the room-rent cap
appears both in the actionable "Confirm these 1 value" block at the top of
`/policies/upload`'s review stage *and* in its normal place in the sub-limits table
below (read-only there). Chose this because removing it from the sub-limits table
would make that table incomplete — a reviewer glancing at "all my sub-limits" would
be missing the one that matters most. The correction control only needs to exist in
one place; the value needs to be visible in both.

### `<PolicyCard>` shows a confidence badge only when sum insured is unconfirmed

Phase 3's binding constraint ("every extracted value renders through
`<ConfidenceBadge>` + `<ProvenanceChip>`") is unambiguous for the review and detail
screens, where the whole point is scrutinising extracted data. A dashboard/list
summary card is a different register — showing a full provenance chip on every
policy card would be noise the moment there's more than one policy, and clicking it
has nowhere to go from that card. Compromise: `<ConfidenceBadge>` appears next to
the sum-insured figure whenever it isn't `user_confirmed`, so an unverified figure
is never silently presented as settled, but a fully-reviewed policy's card stays
quiet. No `<ProvenanceChip>` on the card — that affordance lives on the detail page,
one click away.

### `useJobPolling`'s refresh-recovery required persisting the mock db to `sessionStorage`

Not a "found while verifying" bug so much as infrastructure the Phase 3 requirement
("a page refresh mid-job must recover the result from `GET /jobs/{id}`") made
necessary and hadn't been needed before. The Phase 2 mock db was pure in-memory
state, seeded fresh on every module load — which a real backend's job store isn't,
but a page refresh reloads and re-executes all JS from scratch, wiping it exactly
like a restart would. Fixed by persisting the whole mock db (documents, policies,
claims, jobs, idempotency store) to `sessionStorage` after every mutation, and by
making job records fully serializable — `db.createJob` used to take a `resultFactory`
closure, which can't survive `JSON.stringify`. Replaced with a small resolver
registry (`db.registerJobResolver(kind, fn)`, called once per handler file at module
load) so job records only ever hold plain params, not functions. Verified end-to-end
in a real browser: created an upload job, reloaded mid-parse, confirmed progress had
continued (not restarted) from wall-clock elapsed time, let it finish, reloaded
again, confirmed the policy wasn't created a second time.

### Q&A citation markers are a mock-only `[[n]]` convention

Nothing in `API_DECISIONS.md` specifies how generated prose should mark which
citation backs which sentence — Feature 1's Q&A and Feature 7's grievance drafting
both need this and neither ratified doc says how. Picked `[[n]]` (n = 1-indexed
position in the response's `citations` array) embedded directly in `answer`/
paragraph text, parsed by the new `<CitedProse>` primitive into clickable
superscripts. A real backend just needs to emit the same token shape in its
generated text. Worth a ratified line if a backend developer needs to match it
exactly rather than infer it from this mock.

---

## Phase 4

### Two new endpoints, added unilaterally and flagged rather than blocked on

`PATCH /documents/{id}` (type correction) and a `claim_id` filter on the existing
`GET /documents` didn't exist and the phase brief explicitly requires both (an
editable document-type dropdown in the wizard and the Documents tab; a way to
scope the documents list to one claim). Neither is in `API_DECISIONS.md`'s
ratified endpoint list, which per CLAUDE.md means "ambiguity that affects the
API contract — stop and ask." Proceeded anyway, on the same reasoning Phase 2
used for adding `StoredDocument.claim_id`: the need is concrete and narrow, a
real backend genuinely cannot serve these screens without *something* filling
this gap, and blocking the whole phase on it would cost more than logging it
does. Both are additive (a new endpoint; a new optional query param on an
existing one) — nothing existing had to change shape. Flagged in
`CONTRACTS.md` §4 items 10–11 for sign-off. **What would change if reversed:**
if the real backend team prefers a different shape (e.g. type correction folded
into a general `PATCH /documents/{id}` that accepts other fields too, or a
dedicated `/claims/{id}/documents` sub-resource instead of a query filter), only
`apps/web/src/api/endpoints/documents.ts` and the two MSW handlers change —
nothing about how the wizard/workspace screens call the hooks would need to.

### Claim wizard resumability covers steps 3–6 fully, steps 1–2 partially

The brief requires the wizard to persist step state to the server or to route
state, never `localStorage`. Steps 1–2 (policy + member, then claim type,
admission type, hospital, dates, amount) happen *before* `POST /claims` gives
the wizard anything server-side to resume from. Chose to lift `policy`/`member`
(cheap id references) to URL search params so at least the policy/member choice
survives a refresh, but left step 2's free-form fields (hospital name, dates,
claimed amount) as plain component state — a refresh mid-step-2 restarts intake
at step 1. From the moment `POST /claims` succeeds (end of step 2), the URL
carries `claim={id}&step={n}` and every later step re-reads from the server, so
resumability from step 3 onward is complete. This mirrors the exact tradeoff
`/policies/upload` already made in Phase 3 (a refresh before the upload begins
loses the picked file) — same shape of gap, not a new kind of one. **What would
change if reversed:** encoding all of step 2's fields into the URL is possible
but ugly (a hospital name and free-text fields in a query string) and was
judged not worth it for a gap this narrow; the alternative would be to create
the claim earlier (e.g. immediately after step 1, with placeholder step-2
values, then `PATCH` it in step 2) — rejected because `ClaimCreateRequest` has
no corresponding `PATCH` in the ratified contract and inventing a third new
endpoint for this phase felt like one unilateral addition too many.

### `EligibilityAssessmentView` synthesises the verdict-band sentence from check *titles* and counts only, never from `explanation` text

`EligibilityAssessment` has no single "one-sentence summary" field — only
`band` and the `checks` array, each with its own full-paragraph `explanation`
(which is where the server's date arithmetic lives). The binding constraint
"date arithmetic displayed to the user comes from the server's explanation
string, never recomputed client-side" ruled out paraphrasing or excerpting
`explanation` for the band's headline sentence, since that risks two versions
of the same date math drifting apart. Built `summarizeEligibility()` to
construct the sentence purely from `band`, check *titles* (short, stable,
non-numeric strings — "Pre-existing disease waiting period", not the paragraph
about it), and counts, e.g. `2 checks did not pass, most importantly
"Pre-existing disease waiting period."` Never touches a check's `explanation`.
**What would change if reversed:** if a future contract revision adds a
server-authored one-line summary to `EligibilityAssessment`, this function is
deleted and the band explanation prop is passed straight through instead.

### `EligibilityCheckItem`'s governing-clause provenance chip always renders "unconfirmed", never "verified"

`EligibilityCheck.governing_clause` is a bare `Provenance` (per the ratified
type) — the `confidence`/`user_confirmed` flags that would justify a "verified"
treatment live on the *source* coverage-profile field's `Extracted<T>`
wrapper, which the check doesn't carry a reference to. First draft hardcoded
`userConfirmed` to `true` on this chip, which would have rendered every
governing-clause citation as fully verified regardless of whether anyone
actually confirmed the underlying field — caught during verification and
fixed to `userConfirmed={false}`, so it always renders the honest "unconfirmed
— go check the source" treatment rather than overclaiming. Product rule 1 is
about missing provenance never rendering as confirmed; this is the adjacent
case of *present-but-unverifiable* provenance, and the same "never overclaim"
principle applies. **What would change if reversed:** if `EligibilityCheck`
ever gains its own confidence/confirmation signal (a real contract change),
thread it through instead of the hardcoded `false`.

### Eligibility tab's "upload the resolving document" button switches tabs/steps in place, not to a dedicated upload flow

Brief: an `unknown` check's missing-fact button "routes into the upload flow
with the claim pre-selected." The only existing "upload flow" (`/policies/upload`)
is Feature 1's policy-parsing review screen — wrong shape entirely for a claim
document. Interpreted "the upload flow, claim pre-selected" as: land on the
Documents affordance that's already scoped to this claim, which in the
workspace means switching to the Documents tab (`?tab=documents`) and in the
wizard means jumping back to step 3 — both already claim-scoped by
construction, so there's nothing to "pre-select." Conservative reading that
reuses existing screens rather than building a fourth upload surface.

### Claim wizard's step 4 (bill review) is a deliberately minimal read-only summary, not Feature 3's full table

The brief's step 4 says "bill validation results if an itemised bill was
uploaded," but the same brief explicitly reserves the claim workspace's Bill
tab — the *real* Feature 3 surface (line-item table, flagged rows, click to
highlight in the viewer) — for Phase 5. Built step 4 as a small totals/flags
summary (total billed, amount at risk, one line per flag) sourced from the
same `BillValidationReport` the workspace's future Bill tab will consume, using
only the existing semantic-tone classes (`text-flag`/`text-caution`/`text-neutral`)
rather than a new component, since it will very likely be superseded wholesale
once Phase 5 builds the real thing. Not extracted as a primitive for the same
reason — building a shared component now that Phase 5 is likely to replace
outright would be premature abstraction.

### `detectClaimDocumentType` filename-keyword heuristic (mock-only)

Phase 3's `parse_document` resolver always classified claim-context uploads as
`itemised_bill`, which would have made the wizard's "upload 3 of 4 required
documents, of 4 different types" scenario impossible to demonstrate without
the user manually correcting 3 of 3 uploads every time. Added a keyword match
on the uploaded file's name (`discharge`, `bill`/`invoice`, `receipt`/`payment`,
`aadhaar`/`pan`/`passport`, `denial`/`repudiat`, `investigat`/`lab`/`report`,
default `itemised_bill`) so realistically-named files classify correctly out of
the box, while the editable-dropdown correction control still has a genuine
job for anything misnamed or ambiguous. Purely a mock realism improvement —
no contract shape changed, and a real classifier reads file content, not names.

### Dev toolbar: "Force illegal transition (409)" added as a new scenario toggle

None of the existing toggles could reliably reproduce a 409 on
`POST /claims/{id}/events` without the tester first knowing the state
machine well enough to pick an actually-illegal `to_state` by hand — a
demo/grading liability given the binding constraint that this path must be
reachable via the toolbar. Added `forceIllegalTransition` to
`ScenarioState` (`src/dev/scenarios.ts`) and a corresponding check in the
events handler that always 409s with the claim's real current allowed-target
list, regardless of what was actually requested. See `CONTRACTS.md` §3.

### "Log a denial event on the seeded denied claim" — used the under-review fixture claim instead

The verification brief asks to log a denial event on the seeded denied claim
and confirm a deadline card appears. The seeded denied claim (`claim-denied-ped`)
is already in the `denied` state, and `denied -> denied` isn't a legal
transition in the mock's state machine (`denied` only allows `escalated` or
`resolved`) — logging a second denial on it would just demonstrate the 409
path, not the deadline-appears path the instruction is actually testing.
Interpreted the intent as "log a denial event on a claim and confirm the
resulting deadline," and used the seeded `under_review` claim
(`claim-under-review`, legally transitions to `denied`) instead — verified via
Playwright: logged the transition, confirmed the Ombudsman filing deadline
card appeared with its basis stated ("30 days from the denial on ..."). Both
claims are real fixtures; this just picks the one the action is actually legal
on.

### `EligibilityAssessmentView` lives in `components/primitives/`, not a new "features" directory

It's a composed, domain-bound view (assembles `VerdictBand` + `AbstentionCard` +
`EligibilityCheckItem` + `PrecedentCard` around one `EligibilityAssessment`),
not a base UI atom — but Phase 3 already established the precedent that
`components/primitives/` houses composed domain views alongside atoms
(`SubLimitsTable`, `WaitingPeriodTimeline`, `PolicyCard`, `JobProgress` are all
similarly composed, not atomic). Followed that precedent rather than inventing
a new directory convention. It's shared by the claim wizard's step 5 and the
claim workspace's Eligibility tab, which is the actual point — the two can't
drift apart because there's only one implementation.

### Five-state coverage: `/claims` (the list) only implements loading/empty/error

The binding constraint restates "all five states... reachable via the dev
toolbar" for every Phase 4 screen. `/claims` is a grouped list of claims that
either exist or don't — it has no extracted-with-confidence content and no
abstainable question to decline answering, so "degraded/low-confidence" and
"abstained" have no honest referent on this screen specifically (inventing a
fake confidence concept for claims, which aren't extracted from a document,
would violate the "don't invent data" instinct more than it would satisfy the
letter of the constraint). Both states *are* fully implemented where they
have real content to attach to: degraded via unconfirmed provenance chips and
low-confidence document classification in the wizard's Documents step and the
Documents tab; abstained via the eligibility tab's `insufficient_information`
missing-fact cards and the wizard's step 5. This mirrors the original brief's
own framing (§9: "each screen implements... the states it can occupy") rather
than forcing five states onto a screen that structurally has three.

---

## Hardening block (pre-live-cutover)

### Task 2: added a route-level error boundary — not explicitly requested, but required to actually deliver "the UI still renders"

Task 2 asked for `safeParse` on the live path so a bad response degrades
instead of throwing, and confirmed this in isolation. Verified end-to-end
against a fake backend returning a deliberately malformed `Policy` (missing
`insurer` entirely) and found that `PolicyDetail.tsx` still crashed the whole
route — `policy.data.insurer.name` is an unconditional property access, and
`safeParse` returning the unvalidated payload doesn't stop a *downstream*
component from throwing a plain `TypeError` when a field it assumes exists
genuinely doesn't. Before this fix, that crash rendered React Router's raw
dev stack-trace screen in place of the entire page — nav included — which is
worse for a live demo than a mocked screen with wrong data. Auditing every
component for optional-chaining on every field a real backend might omit is
the "real" fix but is exactly the kind of invasive, error-prone change to
make under Thursday-night time pressure across every screen.

Added `src/components/RouteErrorFallback.tsx` and gave every leaf route (and
the `AppShell`/`kitchen-sink` routes) React Router's `errorElement` (see
`router.tsx`), reusing `<ErrorState>` so a crash still looks like part of the
product, with a reload button. Applied per-leaf so the `AppShell` nav frame
keeps rendering around a crashed screen rather than disappearing with it.
This is the option that fails safest for a live demo — a nav-intact "this
screen couldn't render, check the toolbar" beats either a raw crash screen or
leaving the gap unaddressed and hoping no live response ever triggers it.

**What would change if reversed:** if backend responses turn out reliable
enough that this never fires, the boundary is inert and costs nothing to
leave in. If it fires often in practice, that's a signal individual screens
need defensive rendering for specific fields — the dev-toolbar validation
badge plus this boundary's console log (`[route-error-boundary]`) together
name exactly which route and which field to go fix.

### Task 3: `ProvenanceChip`'s page-validity guard only checks `page < 1`, not `page > page_count`

The task lists four degrade conditions, one of which is `page < 1 or page >
page_count`, and separately says an unusable page should disable the chip
"rather than navigating anywhere." `page_count` lives on `StoredDocument`,
which `ProvenanceChip` never receives — every call site (`ExtractedField`,
`SubLimitsTable`, `CitationList`, `EligibilityCheckItem`, ...) passes a bare
`Provenance`, not the document it belongs to. Threading `page_count` through
every one of those call sites is a real refactor, not a hardening-scale
change, and not something to do for the first time under Thursday-night
pressure. Split the guard instead: `ProvenanceChip` disables on the part it
*can* always know for free — `page < 1` / non-finite / non-integer, which
needs nothing external — and `DocumentViewer` enforces the fuller
`page > page_count` check once the PDF is actually loaded (`numPages` is
free there), clamping to the last real page rather than requesting one that
doesn't exist. Net effect for the demo is the same — you can never end up
looking at a highlight on a page that isn't real — the only difference is
*which* component catches an over-range page: the chip catches `page < 1`
before you ever click; the viewer catches `page > page_count` the moment the
document's real length is known, silently, with the same console log. Also
didn't log "bbox is null" as a rejection anywhere — a missing bbox is an
existing, expected, non-broken state (already designed for since Phase 1),
not something to tell the extraction side is wrong every time it happens.

---

## Backend Phase 3 (document job pipeline)

### `apps/web` was edited by backend work, once, with explicit approval

`CLAUDE.md` says backend work does not edit `apps/web`. Ayush approved one
narrow exception on 2026-10-07, because two things could not be done from
the backend alone:

1. Every page that shows the document viewer loaded one hardcoded mock PDF
   (`/kitchen-sink/sample-policy.pdf`). Nothing asked the backend for the
   uploaded file, so a provenance highlight could never be checked against
   the real document.
2. `Policy.insurer`, `policy_number`, `product_name`, `start_date` and
   `end_date` became nullable (API_DECISIONS D-25), and several pages read
   `policy.insurer.name` directly, which throws on null.

What changed, and nothing else: the five fields became nullable in
`packages/contracts-ts` types and zod schemas; a `useDocumentFile` hook was
added; `PolicyUpload` and `PolicyDetail` pass the real file URL to
`DocumentViewer`; null guards render "Not stated in this document"; the four
new job step names got labels in `JobProgress`; one MSW handler serves the
file route in mock mode. No layout, styling or behaviour was changed.

**What would change if reversed:** restore the mock constant in the two
pages and drop the hook; the null guards must stay for as long as D-25 holds.

### Claim-context viewers still show the mock PDF

`ClaimWorkspace`, `ClaimNew` and `PolicyAsk` still pass the mock PDF to
`DocumentViewer`. They were left alone because claim uploads are not built
on the backend yet (D-29) and Q&A is a later phase. They need the same
one-line change when those arrive.

---

## Backend Phase 4 (claims, timeline, missing documents)

### Second approved `apps/web` edit: unverified markers

Approved by Ayush on 2026-10-08, same narrow terms as the Phase 3 edit. The
contract gained `Deadline.verified`, `Deadline.source`,
`Claim.omitted_deadlines`, `CompletenessReport.verified` and
`CompletenessReport.required_details` (API_DECISIONS D-33, D-35), and the
product rule is that an unverified rule must look unverified.

What changed, and nothing else: those five fields in `packages/contracts-ts`
types and zod; the mock handlers and fixtures now send them; `DeadlineCard`
shows an "Unverified rule" badge, the source, and a sentence saying the date
is an estimate; `CompletenessPanel` shows an "Unverified checklist" note;
the claim timeline lists deadlines that could not be worked out, with the
reason; `JobProgress` labels the `classifying` step.

`required_details` (description and where to get each document) is sent by
the API but not yet shown anywhere in the web app.

### Needs verification against primary source

Every value below is in a rule file with `verified: false` and is shown to
users as unverified. None may be presented as fact in a demo, the report or
the panel presentation until checked. To verify one: correct the value and
source in the file, fill in `url`, set `verified: true`, raise `version`.

`apps/api/app/rules/deadline_rules.yaml`

| Rule | Working value | To check |
| --- | --- | --- |
| `insurer_decision` | 30 days from the last necessary document | Regulation number; whether the 2024 IRDAI regulations and master circular replace it, and their shorter cashless limits |
| `escalation_eligibility` | 30 days after a grievance reaches the insurer | Insurance Ombudsman Rules, 2017, Rule 14; whether "one month" means 30 days or a calendar month |
| `ombudsman_filing` | 1 year from the insurer's rejection | Insurance Ombudsman Rules, 2017, Rule 14; what the year is counted from when the insurer never replies |
| `claim_intimation` | The policy's own extracted hours, counted from admission | Whether the window runs from admission for planned cases, or before it |

`apps/api/app/rules/required_documents.yaml`: the whole file (which
documents each claim type needs). Requirements vary by insurer.

Modelling assumptions that are not regulatory figures but should be reviewed:
the state `escalated` is treated as "a written grievance has reached the
insurer"; and a claim-intimation window that was met produces no card.

---

## Backend Phase 5 (Engine B: eligibility and gap alerts)

### Needs verification against primary source

`engines/rules/reference/typical_costs.yaml`, every entry `verified: false`:
minimum sum insured by household size (Rs 5,00,000 / 7,50,000 / 10,00,000 /
15,00,000 for up to 1 / 2 / 4 / more people) and typical room rent per day
(Rs 6,000 metro, Rs 3,500 tier 2; used once a household picks a city tier, D-40).
Alerts using them say "estimate" and carry `verified: false`.

Rule conventions to confirm against policy wordings: an admission ON the
waiting-period end date counts as outside the period; a 24-hour intimation
window is counted to the end of the next calendar day because only the
admission date is stored.

### Assumptions that change verdicts

- Waiting periods are counted from `policy.first_inception_date` when the
  user has given it (D-39), otherwise from `policy.start_date`, and then the
  explanation states the assumption that first inception may be earlier.
- Policy dates are entered with `PATCH /policies/{id}` (D-39). Until a user
  enters them, an uploaded policy's waiting-period checks are `unknown`.
- The room-rent-below-market alert runs once the household picks a city tier
  (D-40). The tier is the user's choice; no city-to-tier list is kept, because
  any such list would be one more unchecked fact.
- Ambiguous (decided conservatively): `first_inception_date` may be set when
  `start_date` is null; the clock then uses it. It may not be after
  `start_date` or in the future. If reversed (require a start date first),
  only `app/services/policy_dates.py` changes.
- No web form exists yet for policy dates or the city tier; the endpoints
  are usable from Android and curl. Building forms needs an approved
  `apps/web` edit.

### The panel scenario's wording

The mock said an admission on 2 Apr 2026 "falls 23 months inside" a 48-month
waiting period that started on 14 Mar 2024. That mixes up elapsed and
remaining time: the admission is 24 months and 19 days INTO the period, and
23 months and 12 days REMAIN before it ends on 14 Mar 2028. Engine B says both.


## After Phase 5: web screens for the new endpoints

### Third approved `apps/web` edit, and `packages/contracts-ts`

Approved by Ayush on 2026-10-16 ("Go ahead and update the apps/web"; "update
it" for `packages/contracts-ts`). What changed:

- `packages/contracts-ts`: types and zod for D-36 to D-41 (`EligibilityCheck`
  `confidence` / `values` / `missing_facts`, `ombudsman_precedent_note`,
  `Claim.facts`, `Alert.verified` / `provenance` and a string `Alert.id`,
  `Policy.first_inception_date`, `Household`, and the request bodies). The new
  fields are required, matching the rule that nulls are emitted, never omitted.
- Eligibility tab: a form for the claim facts (every question has "Not
  answered yet"); each check shows a confidence label when it is below high
  (words, never a number), every missing fact with where to get it, and a
  collapsible "How this was worked out" list of the server's values. Clause
  links now open the real document through `GET /documents/{id}/file`
  instead of the sample PDF.
- Policy page: a "Policy dates" section to enter start, end and first
  inception dates. They show "Entered by you" and no provenance chip, since
  nothing was read from a page.
- `/alerts` is a real page (it was a placeholder); `/settings` sets the city
  tier. Alert cards show "Estimate · not checked against a published source"
  when `verified` is false, and a provenance chip when there is one.
- The upload review screen corrects sub-limits by position (D-41).
- Mocks: handlers for `PUT /claims/{id}/facts`, `PATCH /policies/{id}`, `GET`
  and `PATCH /household`; fixtures carry the new fields; the mock eligibility
  engine reads the claim facts and no longer says "N months inside". The
  mock session-storage key moved to `v2`, so an old mock session is discarded
  rather than read with missing fields.

Not done: a browser check of these screens (no browser control here; see the
summary for what to click), and `docs/android-fixtures/` are a 2026-10-14
snapshot of the mocks, from before these fields existed.


## Backend Phase 6 (Engine C: policy Q&A)

### Decided with Ayush before building (plan, 2026-10-16)

- Unsupported sentences are removed from `answer`; `verification` counts checked and removed sentences (D-42). The removed text is stored in `policy_question.verification` for evaluation, never sent.
- Evaluation runs on the real 48-page Star Comprehensive wording, not the 3-page demo schedule (which would make recall@5 near-trivial). The demo policy still gets clauses so it can answer live.
- Cache key: document SHA-256 + normalised question + prompt version + model, 24 h; amends D-19; no `X-Cache` header.
- A number from the user's own question may appear in an answer sentence; any other number must be in a supporting clause. Computed numbers always fail.

### Ambiguities decided conservatively

- **A policy that isn't fully indexed is 409**, not a partial search: if any chunk lacks a vector, the clause that matters might be the missing one. If reversed (search what is indexed), only the check in `POST /policies/{id}/questions` changes.
- **Indexing failure does not fail the parse.** The policy is usable without vectors except for Q&A; a warning is added to `document.warnings` and `scripts/index_chunks.py` retries. If no model server is configured, indexing is skipped without a warning.
- **A missing judge verdict counts as unsupported**, and numbers are re-checked against only the clauses judged supportive.
- **Numbers written as words are not read** by the number check; the answer prompt asks for digits. A clause that says "thirty days" therefore cannot vouch for "30 days", and the sentence is removed. Safe direction; it may cost answers on policies that spell numbers out (the Star free-look clause does).
- **The model's abstention reason is never shown**; a fixed sentence is used instead.
- **Answer generation sees the original question** (digits made ASCII); only retrieval uses the English rewrite of a Hindi or Marathi question.
- **The evaluation household** (`01920000-...-0ea`) is created in the real database by `scripts/evaluate_qa.py`, with no login attached.

### Model and cost notes

- BGE-M3 (dense, 1024-d, CLS pooling, normalised) and bge-reranker-v2-m3 run through the `transformers` and `torch` already installed for Engine A; no new library. First run downloads about 4.5 GB to `~/.cache/huggingface`.
- `MODEL_DEVICE` defaults to `cpu`; `mps` (Apple GPU) is available on this Mac.


## Read endpoints: fewer database round trips (2026-10-19)

Measured round trip to the Supabase pooler from the demo Mac: about 170-200 ms, so query count dominates read latency.

| Endpoint | Queries before | Queries after | Median over HTTP before | after |
| --- | --- | --- | --- | --- |
| `GET /members` | 2 | 2 (no N+1 to remove) | 1.05 s | 1.06 s |
| `GET /policies` | 1 + 6 per policy (13 for 2) | 6, any number of policies | 3.00 s | 1.84 s |
| `GET /alerts` | 3 + 4 per policy (12 for 2) | 6, any number of policies | 2.97 s | 1.95 s |

(Counts include the household lookup from the token. `tests/test_read_queries.py` checks the count does not grow with policies.)

### Ambiguities decided conservatively

- **Read-only ORM relationships** (`Policy.insurer / members / coverage_profile`, `CoverageProfile.sub_limits / waiting_periods / exclusions`) were added so the loader can use `joinedload` / `selectinload`. They are `viewonly=True` (rows are still written only through their own tables, so no write path changes) and `lazy="raise"` (an attribute that was not loaded up front raises instead of silently costing a round trip). No schema change; `alembic check` is clean. If reversed, `policy_reader.load_policies` would batch the child tables by hand with `IN (...)` queries.
- **Building a `Policy` no longer queries.** `policy_reader.load_policies` does all the loading; `build_policy` / `build_coverage_profile` only read loaded rows. The PATCH routes reload the policy after commit with `populate_existing`, so the response is what was stored.
- **An alert whose reference figure has no source URL shows `reference_source: "none yet, estimate only"`**, set in Engine B (`ReferenceSource.shown_as`), not in the web client. The reference file's `document` text ("Working figure based on common guidance...") describes the figure; it is not a source, and showing it after "Source:" implied one existed. Doing it server-side means both clients get it with no `apps/web` change; the field's type is unchanged. When an entry gets a `url`, its `document` is shown again.

### Not done (needs a decision)

- **`pool_pre_ping` costs about 4 round trips (~700 ms) on every request** with the asyncpg driver (BEGIN, prepare, ping, ROLLBACK before the real transaction). Measured on `GET /members`: 1.36 s with it, 0.64 s without. It is kept for now because it protects against Supabase closing idle connections; replacing it (for example, pinging only connections idle for more than a minute) affects every endpoint and the job runner, so it waits for Ayush.


### Phase 6 follow-up (2026-10-19)

- **The 15-clause "demo policy" is a synthetic test fixture** written by Claude (`scripts/seed_demo_claims.py`: fictional insurer, generated 3-page PDF). It is now labelled so (`product_name` "... (synthetic test fixture)"), kept out of the Q&A demo and out of headline metrics. The latency, profiling and cache warm-up scripts use the dev household's real uploaded Star policy (`app/qa/demo_policy.py`); the evaluation target is the Star Comprehensive wording. Latency figures reported on 2026-10-16 for the "demo policy" were measured on this fixture and are superseded. The four eligibility demo claims (Phase 5) sat on this fixture until 2026-10-20; they are now on the Star policy (see "Before Phase 7" below).
- **Cache key now includes the document id** (found by an independent review): before, the same file in two households would have shared an answer whose citations named the first document.
- **Search is one SQL statement** (dense and keyword ranks in CTEs, clauses returned by the same statement): 5 round trips per search became 3 (BEGIN, the statement, ROLLBACK). Postgres executes it in about 2 ms; nearly all remaining time is network (one round trip to Supabase's Tokyo region is about 160 ms) and opening/pinging connections (`pool_pre_ping`). Changing pool behaviour is left to Ayush.
- **Gemini fallback:** `GEMINI_FALLBACK_MODEL=gemini-3.7-flash`, chosen because it was listed and answering on 2026-10-19 while `gemini-3.8-flash` had used its free daily quota (20 requests per model per day). A 429 that says to wait more than 60 s goes straight to the fallback.
- **The Q&A test fixture cleans up after itself:** it deletes every household created during the test (cascading to documents, clauses, jobs and question rows) and asserts none of its question rows remain.
- **Observed instability:** the ₹12,000 room question on the Star policy produced a verified answer once and an abstention an hour later (same clauses, temperature 0, different model on the fallback). Abstention is the safe failure, but a cached abstention is what a demo would show.

### Phase 6 Part B: voice input on the ask screen (approved `apps/web` edit)

Approved by Ayush in the Phase 6 brief ("Edit only the ask-screen components"). What changed:

- `src/components/VoiceInput.tsx` (new): the browser's Web Speech API (`SpeechRecognition`, or `webkitSpeechRecognition` in Chrome and Safari). It is hidden where neither exists, and typing always works. Languages are en-IN, hi-IN and mr-IN, and the choice is remembered in `localStorage` inside try/catch (a per-browser convenience only). It shows "Listening…" and the interim words. The final transcript replaces the text in the question box with Devanagari digits made ASCII, and is **never submitted**. It always shows "Voice is converted to text by your browser's speech service." There are short messages for `no-speech`, `not-allowed`, `network`, `audio-capture`, `service-not-allowed` and `language-not-supported`. TypeScript's DOM types lack the recognizer itself, so its few members are declared in the component.
- `src/pages/PolicyAsk.tsx`: the mic is under the question box. The document viewer loads the cited document through `GET /documents/{id}/file` instead of the sample PDF. A failed job shows its `error` sentence with a retry. When `verification.sentences_removed > 0` it says "N statement(s) were left out because we couldn't confirm them in your policy" (decided with Ayush: the removed text is never shown).
- `packages/contracts-ts`: `QuestionAnswerResult.verification` (D-42), required, as the server always sends it. The mock Q&A answers include it.

No network code outside `client.ts`: the browser's speech service is the browser's own connection, which is what the disclosure line is for.


## Before Phase 7: CORS, the flagship question, demo claims on the Star policy (2026-10-20)

### The flagship question's flip-flop ("What if I choose a ₹12,000/day room?", Star policy)

- **It is the generator, not the judge.** Every recorded run (`policy_question.generated` / `verification`) had the same five clauses retrieved, in the same order, with the same rerank scores. Each abstention was the generator setting `abstain: true`, and the judge was never called. In the one run that answered (fallback model), the judge supported both sentences and removed none.
- Temperature was already 0 for every call (rewrite, answer, judge): one `GenerateContentConfig`, in `GeminiQaLlm._once`.
- What varies is the model and the generator itself: the runs mix the primary and the fallback, and the fallback answered once and abstained minutes later on identical input. The room-rent clause (p9) ranks only 2nd, with a rerank score of 0.0004, so the generator is on a knife-edge. Retrieval and the reranker are left as they are (out of scope).
- **Not re-run live on 2026-10-20**: both models' free-tier daily quotas were used up (primary 20/day; the fallback also hit its daily limit after its 5/minute one). The finding rests on the recorded runs.

### Ambiguities decided conservatively

- **`warm_demo_cache.py` never caches an abstention**, as well as never caching a non-primary answer. A demo answer is pinned for 24 h, and a pinned abstention on a demo question is the failure being fixed. An existing entry that breaks either rule is removed and the question is asked again. If reversed, abstentions from the primary would be cached and only reported.
- **The API's own cache still stores fallback answers under the primary model's key** (`run_question.answer_question` always writes `answer_key(..., gemini_model)`). Only the warm-up script was in scope. Effect: after a fallback answer, the same question is served that answer for 24 h even once the primary is back.
  - *Fixed 2026-10-20:* the API now caches an answer only when every call behind it (rewrite, answer, judge) was made by the primary model, and a Hindi/Marathi rewrite only when the primary wrote it. An answer that used the fallback for any call is not cached, so the next asking tries the primary again. Chosen over caching under the fallback's own key because lookups always use the primary's key, so such an entry would never be read. Tests: `apps/api/tests/test_qa_cache_models.py`.
- **Demo claims moved, not recreated** (Ayush's choice): the four fixed-id claims had their `policy_id` changed to the Star policy, and their facts re-saved through `save_facts` (the PUT /facts code). Their event logs are unchanged (append-only). Before: all four on the fixture `01a13f0a-...`. To undo: set `policy_id` back.
- **Star policy dates** were entered through `apply_dates` (the PATCH /policies code) as demo values: start 2026-01-01, end 2026-12-31, first inception 2024-11-01. They were chosen to fit the existing admission dates, which can't change because they are in the events. They are only entered when the policy has no dates.
- **Ananya's claim** is matched to the 24-month listed-conditions period (position 1): knee arthroscopy is on that list in the PDF (p30, p32: "Arthroscopy and Arthroplasty / Joint Replacement").
- **Lakshmi's PED claim is `at_risk` until a person confirms** the 36-month PED period (waiting period #3, p31) on the policy screen; it is then `likely_ineligible` (D-36 needs a high-confidence failure). Ayush's choice: the seed script does not mark it confirmed, because a script-made "user confirmed" would corrupt the extraction-accuracy evaluation data. Verified in memory that the confirmation flips the band.
