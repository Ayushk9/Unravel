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


## Backend Phase 7 (Feature 7: grievance drafting, Ombudsman awards)

### Decided with Ayush before building (plan approved 2026-10-20)

The contract could not carry the brief as written; these additions were approved with the plan and ratified as D-43 to D-45:

- `GrievanceDraft` gains `addressee`, `header_lines`, `closing`, `disclaimer`, `letter_text`, `missing_context`, `generated_at`. Only paragraph text comes from the model.
- New `GET /claims/{id}/grievance-rungs` (row 30) instead of a field on `Claim`, which every screen reads.
- Row 20's errors: 422 (missing key, bad rung including `other`), 409 `idempotency_key_reused`, `rung_not_available`, `policy_not_indexed`.
- Paragraphs cite policy clauses only: claim documents are classified, not read, so a citation of one could not be verified.
- No `[[n]]` markers in paragraphs (`citation_ids` already exists; markers would end up in the copied letter).
- Award ids are `uuid5(namespace, case_reference)`; award grounds are Engine B check ids.

### Fourth approved `apps/web` edit

Approved by Ayush in the Phase 7 brief ("I explicitly approve this apps/web change"). What changed:

- `src/pages/ClaimGrievance.tsx` (new) replaces the `PlaceholderScreen` at `claims/:id/grievance`. It has:
  - a rung selector showing each rung's reason, with "Based on an unverified rule" on unverified rungs and unavailable rungs disabled;
  - a Generate button that makes a new Idempotency-Key per click, with job progress by step;
  - the letter: addressee, subject, header ("not recorded" for null), and paragraphs with citation chips that open the PDF viewer at the clause;
  - unverified paragraphs with an amber left border, an icon and "We couldn't confirm this against your documents. Check or remove it before sending.";
  - a strip showing "N of M paragraphs confirmed" (a count, not a percentage), Copy text (copies the server's `letter_text`), the evidence checklist, and the disclaimer at the top and in the letter.
- States: skeleton, error with retry (rung load, start, job failure), empty (no rung fits yet, with each rung's reason), degraded (some paragraphs unverified) and abstained (`missing_context`, using `AbstentionCard`).
- `src/lib/grievance.ts` (new) holds the page's two pure helpers (default rung, confirmation count), tested in `src/lib/grievance.test.ts` with the contract schemas.
- `src/pages/ClaimWorkspace.tsx`: a "Draft a grievance letter" link in the header when the claim is `denied` or `escalated`.
- `src/api/endpoints/claims.ts` (`useGrievanceRungs`), `src/api/queryKeys.ts`, `src/router.tsx`.
- `mocks/handlers/claims.ts`: the mock draft has the D-43 shape and builds its header from the claim. Its old paragraph claiming that "similar denials ... have previously been overturned by the Insurance Ombudsman" (an invented precedent) is gone; the deliberately unverified paragraph is now a plain overstatement about the policy. There is also a mock rungs handler, and `mocks/db.ts` uses the real step names.
- `packages/contracts-ts`: the D-43 fields, `GrievanceRungOption`, `GrievanceDraftRequest.rung` excluding `other`.

### Ambiguities decided conservatively

- **Grievance drafts run in the questions lane**, one job at a time, because both use Gemini; this keeps quota use predictable. If reversed, a draft and a question could run at once.
- **Search queries** are the recorded denial reason plus the title of each failed or at-risk check, or a fixed "claim settlement procedure" query when there are neither (a delay grievance). Results are merged round-robin, up to 6 clauses.
- **The number check's allowed sources for a paragraph** are its cited clauses plus the claim facts given to the model (the denial note, the diagnosis and the rules' explanations, all from the database), which plays the part that the user's question plays in Q&A. The judge also sees the claim facts, and is told that requests and polite phrases need no support.
- **The denial reason in the header is the user's own note** on the `denied` event, quoted and labelled "as recorded". It is not presented as the insurer's words.
- **An expired Ombudsman window still offers the rung** ("may have passed"), because the one-year rule is unverified. If the rule is verified, this could become `available: false`.
- **A rung requested when not available is refused (409)** rather than drafted with a warning. If reversed, the screen's disabled options would be the only guard.
- **The awards file is read on every request**, so a newly checked award appears without a restart. It is small.
- **`award_to_wire`** lives in `app/api/v1/grievances.py` and is imported by the eligibility route; both routes serve awards.
- **The completeness query moved** from the route into `app/claims/reader.load_attached_documents`, so the route and the draft job read the same documents. Behaviour is unchanged.
- **`_citation` and `_no_progress` in `app/qa/run_question.py`** were renamed to `clause_citation` and `no_progress`, because the grievance job uses them too.
- **Idempotency helpers moved** from `app/api/v1/documents.py` to `app/jobs/idempotency.py`. The upload's 409 message is unchanged.

### Live drafts (2026-10-20): both timed out

Ayush allowed at most two live generations. Both were run for Lakshmi's claim (`…0f3`) at `insurer_grievance_cell` with `scripts/draft_grievance.py`, and both failed at the same point: retrieval completed (model server loaded, clauses found), then the Gemini **draft** call (`gemini-3.8-flash`) did not answer, first within 60 s and then within 120 s. A timeout is not retried and does not fall back (the same rule as Q&A). Nothing was stored. The cause is not diagnosed: a hung request, long model "thinking" on a longer output, or the response schema. No further calls were made.

- Added `GRIEVANCE_LLM_TIMEOUT_SECONDS` (default 120), separate from `QA_LLM_TIMEOUT_SECONDS` (60), because a letter's paragraphs are a longer output than an answer. A job that times out fails with "The drafting service is busy right now. Please try again in a minute."
- The deterministic parts of Lakshmi's letter were rendered from the database with no model call. Insurer, plan and policy number show as "not recorded" (Engine A doesn't extract them, D-25). Every evidence item is unticked, because the demo claim has no documents attached.

### Not done (needs a decision)

- **Web render tests for the five states.** `apps/web` has no DOM test environment (no jsdom or happy-dom, no Testing Library), and CLAUDE.md forbids adding libraries without asking. What is tested: the page's logic and the contract schemas (Vitest), and typecheck, lint and build. To render the page in tests, add `jsdom` and `@testing-library/react` as dev dependencies.

### Needs verification against primary source

- `apps/api/app/rules/grievance_rungs.yaml`: every sentence about the escalation order (the insurer's grievance cell first; Bima Bharosa and the Ombudsman usually expecting a prior complaint to the insurer) and every `source`. All are `verified: false` with `url: null`.
- `apps/api/app/rules/ombudsman_rules.yaml`: the Ombudsman award limit, `value: null`. Sources conflict (§8). It is read into no output; `tests/test_grievance_units.py` fails if any output mentions it.
- `engines/rules/reference/ombudsman_awards.yaml` is empty. Awards are Ayush's to add, each with `checked_by_ayush: true`.

## Phase 7 decisions, Stage A (2026-10-20): identity fields, sample documents, render tests, startup checks

Decided by Ayush after Phase 7 (his answers to the plan's questions): Gemini work waits for a teammate's key. Do the timeout diagnosis and the one live draft first, then upload and classify the sample documents. Store a typed insurer name as a separate text field. Make the sample documents exactly as briefed.

### Fifth approved `apps/web` edit, and two dev dependencies

- **Policy details form** (approved in the brief): `src/components/PolicyDatesForm.tsx` became `PolicyDetailsForm.tsx`.
  - It edits the insurer, product, policy number and the three dates, and sends only the fields that changed.
  - Each value the user entered shows "Entered by you" (from `user_entered_fields`).
  - The policy page's section is now "Policy details". `lib/policyLabels.insurerLabel` falls back to `insurer_name`.
  - The hook `useUpdatePolicyDates` became `useUpdatePolicy`.
  - The mock's PATCH handles the new keys. Mock policies saved in sessionStorage before this get the two new fields filled in when loaded.
- **`jsdom`, `@testing-library/react` and `@testing-library/dom`** (approved). The last is the required peer of the second.
  - The render tests use a per-file `// @vitest-environment jsdom` comment, so no Vitest config file was added.
  - `src/pages/ClaimGrievance.test.tsx` covers the grievance screen's five states, the exact unverified-paragraph sentence, the count strip (no percentage) and Copy text.
  - `apiFetch` is replaced per path, and each answer is parsed by its real zod schema, so the fixtures are checked against the contract too. The PDF viewer is stubbed, because jsdom has no canvas.
  - `npm install` reported existing audit advisories; nothing was changed for them.

### Ambiguities decided conservatively

- **The typed insurer name never creates a row in the shared `insurer` table** (Ayush's choice). `Policy.insurer` stays the reference link; `insurer_name` is the user's text.
- **The form sends only changed fields**, so a value is never re-saved as "entered by you" just because the form was opened and saved.
- **Sample documents** (`scripts/make_sample_documents.py` → `apps/api/sample_documents/`, committed because they are fictional and reproduce the demo):
  - Every page is stamped "SAMPLE DOCUMENT - FICTIONAL PATIENT" at the top and bottom.
  - Dates, amounts, hospitals and diagnoses come from `seed_demo_claims.CLAIMS`. Bill lines add up exactly to the claimed amount.
  - There are no addresses, phone numbers, e-mails or registration numbers.
  - **The denial letters come from "Sample Insurer - Claims Department (fictional)" and quote the policy number SAMPLE-0001; they do not carry Star Health's name as letterhead.** A document styled as a real company's letter is a risk even with a stamp; classification only needs the content of a denial letter. If reversed, the letterhead would name the insurer.
  - **Vikram, Ananya and Ishaan have denial letters although their event logs show no denial** (as briefed). Their letters are dated 14 days after discharge; Lakshmi's uses her denial event's date. It doesn't affect completeness (`denial_letter` is not on any checklist) or eligibility.
  - Ishaan's payment receipt is left out, so 15 files. Every claim will still also show the investigation report and ID proof as missing: the reimbursement checklist requires them and no sample was made (a fake ID proof would not be made at all).
- **A small new PDF writer** (`scripts/sample_pdf.py`) instead of moving the seed's. The seed's writer is tied to its fixture's bounding-box layout (the clause provenance); moving it risked that.
- **`scripts/upload_sample_documents.py`** (Stage B) uploads through `POST /documents` to a server Ayush has started. It skips a file already attached to its claim, so it is safe to re-run after the 24-hour idempotency window.

### Startup checks run only on the test database

On 2026-10-20 the health, 404 and 401 checks were run by building the app in-process against `apps/api/.env`. That ran the startup routine on the **dev** database, which failed two `answer_question` jobs stuck in `running` since 19 Oct, 12:10 UTC (never started). The next server restart would have failed them anyway, but it was an unplanned write. From now on these checks run through `tests/test_startup_routine.py`, which runs the real startup routine and the three checks in the temporary test schema, or against a server Ayush started.

## Phase 7 decisions, Stage B (2026-10-20): the draft timeout, diagnosed

Run with the teammate's key (ends `vHWQ`), with `scripts/diagnose_draft_call.py`: Lakshmi's real draft prompt (6 clauses, 10,812 characters, **2,648 tokens** by `count_tokens`), one streamed call per run, no retry.

| Call | Model | Options | Time to first byte | Total | Thinking tokens | Output tokens | Result |
|---|---|---|---|---|---|---|---|
| 1 | gemini-3.8-flash | model default | 168.6 s | 168.7 s | 1,475 | 92 | valid JSON |
| 2 | gemini-3.8-flash | thinking LOW, max 2,048 | 54.0 s | 54.0 s | none reported | 9 | abstained |
| 3 | gemini-3.7-flash | thinking LOW, max 2,048 | 29.9 s | 29.9 s | none reported | 9 | abstained |

- **Cause:** the model's unbounded thinking, on top of a large wait on Gemini's side for this free key. The wait is not proportional to the work: 9 output tokens and no thinking still took 30–54 s. Both earlier timeouts (60 s and 120 s) fit call 1's 168.6 s.
- **Change:** the draft call now uses `thinking_level=LOW` and `max_output_tokens=2048`; the support judge uses `MINIMAL` and `1024` (`app/grievance/llm.py`, with the reasons in a comment). `GRIEVANCE_PROMPT_VERSION` is `grievance-v2`. Q&A calls are unchanged (they send no thinking options); a test checks both.
- **Why these levels:** the draft is composition from at most 6 given clauses under strict citation and honesty rules, so a little reasoning (LOW) is kept. The judge gives one entailment verdict per clause, which needs none (MINIMAL). The caps are well above the largest valid output (5 × 1,200-character paragraphs is about 1,500 tokens).
- **The 4th diagnostic call was not used.**

### The live draft (Lakshmi, insurer_grievance_cell)

- One draft call (`gemini-3.8-flash`, LOW): draft 14.3 s, retrieval 17.1 s (including the model load). Stored as `grievance_draft` `01a15a70-0027-77bb-9c08-7d58464d9054`.
- **The model abstained**, as both diagnostic calls had. The facts block includes the rules' own result (PED waiting period failed, from the policy's 36-month clause), and the prompt says to abstain when the clauses give no honest ground. So the letter has the full deterministic header (now with insurer, plan and SAMPLE-0001) and asks the user to write their own reasons. No judge call was made, because there was nothing to judge.
- **Not changed without Ayush:** the prompt was not loosened to make the model argue. A denial the policy supports is the case where an honest draft has no argument to make.

**Gemini calls on the new key so far:** 4 generate (3 diagnostic, 1 draft) and 3 `count_tokens` (a separate quota).

## Phase 7 decisions, Stage B continued (2026-10-22): sample uploads, procedural requests, a wrongful denial

### Sample documents attached (the normal upload flow, classifier live)

- **15 documents** were uploaded through `POST /documents` to Ayush's restarted server with `scripts/upload_sample_documents.py`. All 15 were classified correctly with high confidence (discharge summary, itemised bill, payment receipt, denial letter), using **15 Gemini calls**.
- **Rajan's 4 documents** (claim 5, below): the denial letter, discharge summary and bill classified correctly. The **payment receipt failed** at first (`classify_failed`, retryable). It was the 19th classification call of that quota day; the next Gemini calls minutes later got 429 RESOURCE_EXHAUSTED on both models. After the quota reset, `upload_sample_documents.py` (which now soft-deletes a document whose classification failed and uploads it again under a new key) classified it as `payment_receipt` (high), using 1 call. Rajan's claim is missing only the investigation report and ID proof, like the others.

### D-47: fixed procedural requests (approved by Ayush)

- See `API_DECISIONS.md` D-47.
- **What "our assessment agrees" means:** the band is `likely_ineligible`. The denial reason is the user's free text and is never keyword-matched, so agreement is with the claim being ineligible, not a matched reading of the insurer's words. If reversed (match the reason to a check), a reason-to-check mapping chosen by the user would be needed.
- **Model paragraphs are kept** when the templates are added. In the "our rules agree" case the model has so far abstained, so in practice the letter is all template text. If it ever argues while the note says "does not dispute it", the two would conflict; flagged here rather than silently dropping verified text.
- **Template paragraphs carry `verified: false`**, so a client that doesn't know `source` flags them rather than presenting them as checked.
- **Web:** template paragraphs are labelled "Standard request (template text)" with no unconfirmed flag; the note is shown above the letter; the "N of M confirmed" strip counts model paragraphs only. The MSW mock sends `source` and `assessment_note`.

### A fifth demo claim: a wrongful PED denial (Ayush chose a second sample policy)

- **Why a second policy:** the Star policy's first inception is 1 Nov 2024, so its 36-month PED period ends 1 Nov 2027, after today. No admission on it can yet be outside the period.
- **SAMPLE-0002** (`01920000-…-0000000000a2`): a new policy row on the same Star wording document, with a **copy of the Star policy's extracted terms** (values, provenance, user confirmations). Its user-entered details were set through the PATCH code: Star Health and Allied Insurance Co. Ltd., Star Comprehensive Insurance Policy, start 1 Jan 2026, end 31 Dec 2026, first inception 1 Jun 2021.
  - **Its terms are copies and are not extraction-accuracy data.** Any accuracy count must exclude SAMPLE-0002.
  - `app/qa/demo_policy.find_real_policy` excludes it, so the Q&A scripts keep using the uploaded Star policy.
- **Rajan Rao** (a fictional member, `…000015`, created by the seed): planned admission 14 Jul 2026 to 18 Jul 2026, Rs 2,40,000, hypertensive heart disease, first diagnosed 10 Apr 2019 (pre-existing). Denied 20 Aug 2026 with "Denied as a pre-existing disease within the waiting period".
- **Eligibility (live, through the server):** `likely_eligible`. PED satisfied ("Your continuous cover started 1 Jun 2021; the 36-month waiting period ended on 1 Jun 2024"); room rent and sum-insured checks are unknown (not extracted for this policy).

### The live wrongful-denial draft (Rajan, insurer_grievance_cell)

- **A bug found live:** `gemini-3.8-flash` rejects `thinking_level=MINIMAL` with 400 INVALID_ARGUMENT. The first attempt's draft call succeeded (after two 503 retries), then the judge call failed on this. The fake-client test could not see it. **The judge now uses LOW**, the lowest level the model accepts. `GRIEVANCE_PROMPT_VERSION` is `grievance-v3`.
- **Second attempt:** `grievance_draft` `01a16271-1416-7e69-ae6e-8006e01b4678`. Timings: retrieval 13.8 s, draft 24.3 s, verification 13.5 s. Both calls were answered by `gemini-3.8-flash`, after one 503 retry.
- **Three model paragraphs, all verified (citation precision 1.00)**, citing pages 31 (PED clause: continuous cover and the waiting period), 30 (the optional buy-back reducing the PED period) and 41 (portability credits). The third paragraph had cited two clauses; the judge rejected one and only the supported citation was kept. No template paragraphs were added (one survived, and the rules do not agree with the denial).
- **Observation for review:** the paragraphs ask the insurer to clarify and reconsider. None states the strongest fact, that the 36-month period counted from first inception (1 Jun 2021) ended on 1 Jun 2024, because the prompt forbids dates in paragraphs (the header carries the facts). If Ayush wants the letter to say so, it should be a deterministic sentence built from the eligibility check's values, not model text.

**Gemini calls on the new key, 2026-10-22:**
- 19 classifications before the reset (18 succeeded; the 19th failed);
- 2 refused with 429;
- after the reset: 1 draft and 1 rejected judge (400), then 1 draft and 1 judge, then 1 classification.

## Phase 7, 2026-10-22: the rules-built opening, a stricter prompt, "Before you send" (D-48)

### Decided with Ayush

- **The denial ground is the user's choice**, not read from the reason text: a new claim fact, `denial_ground` (an eligibility check id), with a dropdown in the claim facts form ("If the insurer denied this claim, which ground did it give?"). The seed sets `ped_waiting_period` for Lakshmi and Rajan.
- **The ID-proof sample is plainly fictional:** "IDENTITY PROOF (SAMPLE) - NOT A GOVERNMENT DOCUMENT", SAMPLE-ID-0005, with no government layout, emblem or number format. Classified as `id_proof` (high).

### What was built

- **The opening paragraph** (`app/grievance/rules_text.py`) is fixed text from the chosen ground's check values, citing its governing clause. It is written only for the three date-counted waiting-period checks; any other ground gets none rather than improvised text.
- **The model's prompt** (grievance-v4) only receives the checks that support the policyholder, and must not raise benefits the facts don't mention, or conditions against the policyholder, in the letter. Those go to `conditions`, which become "Before you send" notes, verified by the same judge call. Calls per draft stay at 2.
- **The evidence checklist** ticks "Policy wording attached" when the claim's policy document is uploaded.
- **Rajan's investigation report and identity proof** were uploaded through Ayush's server: 2 classification calls, both correct (high). His checklist is now complete.
- **Evaluation exclusion:** `app/qa/demo_policy.EXCLUDED_FROM_EVALUATION` lists the synthetic fixture and SAMPLE-0002. `find_real_policy` and `scripts/evaluate_qa.py` use it. A test fails if any non-seed script picks a policy without going through it. **There is no extraction-accuracy script yet; when one is written it must use this list.**
- **Web (an approved edit):**
  - the claim facts form's ground dropdown;
  - the grievance screen labels a rules paragraph "From our eligibility checks (fixed text)" with its citation chip, and shows a "Before you send" panel ("For you only. These are not in the letter."), with unconfirmed model notes flagged;
  - the confirmation count ignores rules and template paragraphs;
  - a render test covers both.

### The regenerated live draft (Rajan, `grievance_draft 01a16390-8328-7fce-8b41-6b526c1b3c10`)

- 2 calls on `gemini-3.8-flash` (after two 503 retries). Retrieval 25.1 s, draft 28.5 s, verification 22.4 s.
- **The letter has one argument paragraph, the rules opening** (cover from 1 Jun 2021, 36 months, ended 1 Jun 2024, admitted 14 Jul 2026), citing page 31.
- Under the stricter prompt **the model wrote no paragraph of its own**: it abstained and returned four conditions, all judged supported (pp. 31 and 32), shown in "Before you send" with the two rules notes. The earlier version's paragraphs about the optional buy-back and portability are gone, as asked.
- **A bug found in this draft and fixed in code:** with the rules opening present, the draft still carried the model-abstention sentence ("…the letter has no argument paragraphs. Add your own reasons…"). That was untrue. It appears only on the screen, never in the letter. A draft with a rules opening now has no `missing_context` (tested). The stored row keeps what was produced; it was not regenerated, to save a call.
- **Observation for review:** one condition (the 30-day initial exclusion, p32) cannot apply to cover held since 2021. It is shown but harmless. Filtering conditions by relevance would need either more model judgement or more rules; not done.

**Gemini calls on the new key since the reset (12:30 IST, 22 Oct):**
- first 1 draft and 1 rejected judge (400), then 1 draft and 1 judge, then 1 receipt classification;
- now 2 classifications (Rajan's report and ID proof), and 1 draft and 1 judge.

## Rule verification by Ayush, and closing Phase 7 (2026-10-23)

### Needs verification: resolved and still open

Ayush checked these against the official text. Source for 1 and 2: [Insurance Ombudsman Rules, 2017 (as amended till 09.11.2023)](https://www.cioins.co.in/notification/Insurance%20Ombudsman%20Rules,%202017(%20as%20amended%20till%2009.11.2023).pdf).

1. **RESOLVED: the Ombudsman award ceiling is ₹50 lakh, including relevant expenses.** Rule 17(3) proviso (ii), substituted by G.S.R. 828(E) dated 9.11.2023.
   - `apps/api/app/rules/ombudsman_rules.yaml`: `value: 500000000` (paise), `verified: true`, with the URL.
   - It appears only in the Ombudsman rung's reason, when that rung is offered, in one fixed sentence: "By the Insurance Ombudsman Rules, the Ombudsman can award at most ₹50,00,000, including relevant expenses. This is a limit on what can be awarded, not an amount you can expect."
   - It never appears in a letter, and disappears everywhere if `verified` goes back to false. All three are tested.
2. **PARTLY RESOLVED: the Ombudsman filing window is 1 year (Rule 14(3)(b)), but our trigger is wrong.**
   - By Rule 14(3)(a) a complaint lies only after a written representation to the insurer, and its rejection, an unsatisfactory reply, or no reply within one month. The year runs from the reply or rejection, or from one month after the representation if there was no reply.
   - `ombudsman_filing` now cites Rule 14(3)(a) and (b) with the URL, but **stays `verified: false`** until the D-49 plan (below) is approved and built. Ayush asked to see the plan before any coding; it changes the claim state machine (D-31) and the contract.
   - Rule 17(4) (award within 3 months of receiving all requirements) is to be shown as information only.
3. **STILL NOT VERIFIED: the insurer decision deadline.** IRDAI/HLT/REG/CIR/152/06/2020 says 30 days from the last necessary document (45 if investigated), with interest at bank rate + 2%. The Master Circular on Protection of Policyholders' Interests, IRDAI/PP&GR/CIR/MISC/117/9/2024 (5 Sep 2024), appears to set 15 days from submission of the claim for non-cashless health claims. `insurer_decision` now names both documents and says "being confirmed". Its value is unchanged (30 days) and it stays `verified: false`.

### Closing items

- **Citation precision with no model paragraphs:** kept as the number `0` on the wire, not made nullable, because a nullable change would break any client (Android) that reads it as a number. Both clients show **"No model-written paragraphs to check"** instead of a figure; recorded as a clarification under D-47. The web strip and `scripts/draft_grievance.py` do so. If reversed (null on the wire), it is a breaking change needing both clients updated together.
- **Settled conditions are dropped from "Before you send":**
  - Each model condition carries `restates_check`, the id of the eligibility check whose own requirement it restates, or `"none"`. It is set in the same draft call (prompt `grievance-v5`); there is no extra call.
  - Code drops a condition whose check our rules found **satisfied** (`run_draft.drop_settled_conditions`) before judging, and the record keeps it under `conditions_dropped`.
  - A further requirement no check evaluates (for example the PED declaration condition) is tagged `"none"` and always kept.
  - **Why a tag and not the cited clause:** both kinds cite the same PED clause, so the clause alone cannot tell them apart. The tag is model output and could be wrong; a wrong tag on a real requirement would hide it. That risk is accepted as smaller than showing settled noise.
- **`scripts/regenerate_demo_drafts.py`** (not run): drafts Lakshmi's and Rajan's letters as real `generate_grievance_draft` jobs through the runner's own job function, prints each screen link and every Gemini attempt by model. Job rows last 24 h after finishing, so it must run within 24 h of the panel. A test checks the counter sees retries and the fallback.

### Proposed, awaiting approval: D-49, Ombudsman timing from the grievance to the insurer

1. **Claim states** (amends D-31):
   - New: `grievance_sent` (a written representation to the insurer) and `insurer_replied` (rejected, or replied unsatisfactorily).
   - `escalated` narrows to "a complaint filed beyond the insurer (Ombudsman)".
   - Graph: `denied → grievance_sent | resolved`; `grievance_sent → insurer_replied | escalated | resolved`; `insurer_replied → escalated | resolved`; `escalated → resolved`.
   - Existing `escalated` events stay as written (append-only).
2. **Deadlines** (amends D-33): `ombudsman_filing` counts from the latest `insurer_replied`, else from `grievance_sent` plus one month. The rule-file format gains a "trigger, else trigger plus offset" form. `escalation_eligibility` becomes "you may approach the Ombudsman from": `grievance_sent` plus one month, shown only while no reply is recorded. Both become `verified: true` once built.
3. **Ombudsman rung:** offered only in `insurer_replied`, or in `grievance_sent` once a month has passed. After a denial alone it is not offered, with a reason saying to write to the insurer's grievance cell first. Rule 17(4) as an information line.
4. **Contract:** two `ClaimState` values (clients already have an escape hatch), changed deadline ids and labels, and `POST /claims/{id}/events` accepting the new states. The web timeline and state badges get labels.

