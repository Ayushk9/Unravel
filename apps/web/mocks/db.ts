/**
 * In-memory mock "database", seeded from mocks/fixtures/ and mutated by
 * handlers for the lifetime of the browser tab. Persisted to sessionStorage
 * after every mutation and rehydrated on load — a real backend's job state
 * survives a page refresh, and Phase 3 requires the mock to demonstrate that
 * (refreshing mid-parse must recover the running job, not restart it). A
 * pure in-memory store can't do that across a full page reload, so this is
 * not optional. sessionStorage (not localStorage) so a closed tab still
 * starts fresh, matching "resets on reload" for a genuinely new session.
 */
import type { JsonBodyType } from "msw";
import type { Claim, ClaimEvent, ClaimState, CoverageProfile, Job, JobKind, Policy, StoredDocument } from "@/api/types";
import * as fixtures from "./fixtures";
import { genId } from "./utils";

function clone<T>(value: T): T {
  return structuredClone(value);
}

const STORAGE_KEY = "unravel:mock-db:v1";

interface JobRecord {
  job: Job<unknown>;
  createdAt: number;
  durationMs: number;
  /** Plain, serializable inputs — never a closure, so this record survives JSON round-tripping through sessionStorage. */
  params: Record<string, unknown>;
  cachedResult?: unknown;
  failed?: boolean;
}

interface PersistedShape {
  documents: StoredDocument[];
  policies: Policy[];
  claims: Claim[];
  jobs: [string, JobRecord][];
  idempotency: [string, { status: number; body: JsonBodyType }][];
}

function loadPersisted(): PersistedShape | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as PersistedShape) : null;
  } catch {
    return null; // sessionStorage unavailable (private mode, etc.) — fall back to fixtures, in-memory only
  }
}

function persist(): void {
  try {
    const payload: PersistedShape = {
      documents,
      policies,
      claims,
      jobs: [...jobs.entries()],
      idempotency: [...idempotencyStore.entries()],
    };
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  } catch {
    // Storage full or unavailable — the mock keeps working for the rest of
    // this tab's life, it just won't survive the next refresh.
  }
}

const persisted = loadPersisted();

// --- documents ---
let documents: StoredDocument[] = persisted ? persisted.documents : clone(fixtures.documents);

export function listDocuments(): StoredDocument[] {
  return documents.filter((d) => !d.deleted_at);
}
export function getDocument(id: string): StoredDocument | undefined {
  return documents.find((d) => d.id === id);
}
export function addDocument(doc: StoredDocument): void {
  documents.push(doc);
  persist();
}
export function updateDocument(id: string, patch: Partial<StoredDocument>): StoredDocument | undefined {
  const doc = getDocument(id);
  if (!doc) return undefined;
  Object.assign(doc, patch);
  persist();
  return doc;
}
export function softDeleteDocument(id: string): StoredDocument | undefined {
  const doc = getDocument(id);
  if (!doc) return undefined;
  doc.deleted_at = new Date().toISOString();
  persist();
  return doc;
}

// --- policies ---
let policies: Policy[] = persisted ? persisted.policies : clone(fixtures.policies);

export function listPolicies(): Policy[] {
  return policies;
}
export function getPolicy(id: string): Policy | undefined {
  return policies.find((p) => p.id === id);
}
export function addPolicy(policy: Policy): void {
  policies.push(policy);
  persist();
}

/** D-15: dotted-path field correction. Only the fields the review screen actually corrects are addressable. */
export function patchCoverageField(
  policyId: string,
  fieldPath: string,
  value: string | number | boolean | null,
  userConfirmed: boolean,
): { ok: true; policy: Policy } | { ok: false; reason: "policy_not_found" | "profile_not_ready" | "unknown_field" } {
  const policy = getPolicy(policyId);
  if (!policy) return { ok: false, reason: "policy_not_found" };
  if (!policy.coverage_profile) return { ok: false, reason: "profile_not_ready" };

  const profile = policy.coverage_profile;
  const segments = fieldPath.split(".");

  // sum_insured | co_pay_percent | intimation_deadline_hours
  const topLevelKey = segments[0];
  if (segments.length === 1 && topLevelKey !== undefined && topLevelKey in profile) {
    const field = profile[topLevelKey as keyof CoverageProfile];
    if (field && typeof field === "object" && "value" in field) {
      (field as { value: unknown }).value = value;
      (field as { user_confirmed: boolean }).user_confirmed = userConfirmed;
      persist();
      return { ok: true, policy };
    }
  }

  // sub_limits.<category>.cap_amount — addressed by category label per
  // API_DECISIONS.md D-15's own example ("sub_limits.room_rent.cap_amount"),
  // not array index.
  if (segments[0] === "sub_limits" && segments.length === 3 && segments[2] === "cap_amount") {
    const subLimit = profile.sub_limits.find((s) => s.category === segments[1]);
    if (subLimit) {
      subLimit.cap_amount.value = typeof value === "number" ? value : subLimit.cap_amount.value;
      subLimit.cap_amount.user_confirmed = userConfirmed;
      persist();
      return { ok: true, policy };
    }
  }

  // waiting_periods.<kind>.months — addressed by kind label, same reasoning
  // (D-15's other example: "waiting_periods.pre_existing.months").
  if (segments[0] === "waiting_periods" && segments.length === 3 && segments[2] === "months") {
    const waitingPeriod = profile.waiting_periods.find((w) => w.kind === segments[1]);
    if (waitingPeriod) {
      waitingPeriod.months.value = typeof value === "number" ? value : waitingPeriod.months.value;
      waitingPeriod.months.user_confirmed = userConfirmed;
      persist();
      return { ok: true, policy };
    }
  }

  return { ok: false, reason: "unknown_field" };
}

// --- members / alerts / ombudsman / benchmarks — read-only fixtures ---
export function listMembers() {
  return fixtures.members;
}
export function listAlerts() {
  return fixtures.alerts;
}
export function listOmbudsmanAwards() {
  return fixtures.ombudsmanAwards;
}
export function listBenchmarks() {
  return fixtures.benchmarks;
}

// --- claims ---
let claims: Claim[] = persisted ? persisted.claims : clone(fixtures.claims);

export const CLAIM_TRANSITIONS: Record<ClaimState, ClaimState[]> = {
  intimated: ["documents_submitted", "queried"],
  documents_submitted: ["under_review", "queried"],
  under_review: ["queried", "approved", "denied"],
  queried: ["documents_submitted", "under_review"],
  approved: ["resolved"],
  denied: ["escalated", "resolved"],
  escalated: ["resolved"],
  resolved: [],
  unknown: [],
};
// Not specified by API_DECISIONS.md — this graph is a mock-only assumption
// about claim lifecycle shape, not a ratified rule. See DECISIONS.md.

export function computeCurrentState(events: ClaimEvent[]): ClaimState {
  return events.at(-1)?.to_state ?? "intimated";
}

export function listClaims(): Claim[] {
  return claims.map((c) => ({ ...c, current_state: computeCurrentState(c.events) }));
}
export function getClaim(id: string): Claim | undefined {
  const claim = claims.find((c) => c.id === id);
  if (!claim) return undefined;
  return { ...claim, current_state: computeCurrentState(claim.events) };
}
export function addClaim(claim: Claim): void {
  claims.push(claim);
  persist();
}

export function appendClaimEvent(
  claimId: string,
  toState: ClaimState,
  occurredAt: string,
  note: string | null,
): { ok: true; claim: Claim } | { ok: false; reason: "not_found" } | { ok: false; reason: "illegal_transition"; allowed: ClaimState[] } {
  const claim = claims.find((c) => c.id === claimId);
  if (!claim) return { ok: false, reason: "not_found" };

  const currentState = computeCurrentState(claim.events);
  const allowed = CLAIM_TRANSITIONS[currentState];
  if (!allowed.includes(toState)) {
    return { ok: false, reason: "illegal_transition", allowed };
  }

  const event: ClaimEvent = {
    id: genId("event"),
    claim_id: claimId,
    from_state: currentState,
    to_state: toState,
    occurred_at: occurredAt,
    note,
    source: "user",
  };
  claim.events.push(event);
  claim.current_state = computeCurrentState(claim.events);
  persist();
  return { ok: true, claim };
}

export function documentsForClaim(claimId: string): StoredDocument[] {
  return listDocuments().filter((d) => d.claim_id === claimId);
}

// --- jobs ---
type JobResolver = (params: Record<string, unknown>) => unknown;
const jobResolvers: Partial<Record<JobKind, JobResolver>> = {};

/** Each handler file registers the resolver for the job kind it owns, once, at module load — keeps db.ts generic and resource logic in its own handler file. */
export function registerJobResolver(kind: JobKind, resolver: JobResolver): void {
  jobResolvers[kind] = resolver;
}

const jobs = new Map<string, JobRecord>(persisted?.jobs ?? []);

const JOB_STEPS: Record<JobKind, string[]> = {
  parse_document: ["classifying_pages", "extracting_tables", "structuring_coverage_profile"],
  answer_question: ["retrieving_clauses", "reranking", "generating_answer"],
  generate_grievance_draft: ["assembling_evidence", "drafting_paragraphs", "verifying_citations"],
};

export function createJob(kind: JobKind, durationMsRange: [number, number], params: Record<string, unknown>): Job<unknown> {
  const job_id = genId("job");
  const durationMs = durationMsRange[0] + Math.random() * (durationMsRange[1] - durationMsRange[0]);
  const job: Job<unknown> = { job_id, kind, status: "queued", progress: null, result: null, error: null };
  jobs.set(job_id, { job, createdAt: Date.now(), durationMs, params });
  persist();
  return job;
}

export function getJob(jobId: string): Job<unknown> | undefined {
  const record = jobs.get(jobId);
  if (!record) return undefined;

  const elapsed = Date.now() - record.createdAt;
  if (elapsed >= record.durationMs) {
    if (record.cachedResult === undefined && !record.failed) {
      const resolver = jobResolvers[record.job.kind];
      try {
        record.cachedResult = resolver ? resolver(record.params) : null;
      } catch {
        record.failed = true;
      }
      persist();
    }
    if (record.failed) {
      return { ...record.job, status: "failed", progress: { step: "failed", percent: 100 }, result: null, error: "This job failed. Try uploading again." };
    }
    return { ...record.job, status: "succeeded", progress: { step: "done", percent: 100 }, result: record.cachedResult };
  }

  const percent = Math.min(99, Math.floor((elapsed / record.durationMs) * 100));
  const steps = JOB_STEPS[record.job.kind];
  const stepIndex = Math.min(steps.length - 1, Math.floor((percent / 100) * steps.length));
  const status = percent < 10 ? "queued" : "running";
  return { ...record.job, status, progress: { step: steps[stepIndex] ?? "processing", percent } };
}

// --- idempotency (D-13) ---
const idempotencyStore = new Map<string, { status: number; body: JsonBodyType }>(persisted?.idempotency ?? []);

export function getIdempotentResponse(key: string): { status: number; body: JsonBodyType } | undefined {
  return idempotencyStore.get(key);
}
export function storeIdempotentResponse(key: string, status: number, body: JsonBodyType): void {
  idempotencyStore.set(key, { status, body });
  persist();
}

export function resetDb(): void {
  documents = clone(fixtures.documents);
  policies = clone(fixtures.policies);
  claims = clone(fixtures.claims);
  jobs.clear();
  idempotencyStore.clear();
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}
