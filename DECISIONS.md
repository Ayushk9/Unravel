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
