/**
 * In-memory mock "database", seeded from mocks/fixtures/ and mutated by
 * handlers for the lifetime of the page. Resets on reload — that's
 * intentional for a mock, not a bug to fix.
 */
import type { JsonBodyType } from "msw";
import type { Claim, ClaimEvent, ClaimState, CoverageProfile, Job, JobKind, Policy, StoredDocument } from "@/api/types";
import * as fixtures from "./fixtures";
import { genId } from "./utils";

function clone<T>(value: T): T {
  return structuredClone(value);
}

// --- documents ---
let documents: StoredDocument[] = clone(fixtures.documents);

export function listDocuments(): StoredDocument[] {
  return documents.filter((d) => !d.deleted_at);
}
export function getDocument(id: string): StoredDocument | undefined {
  return documents.find((d) => d.id === id);
}
export function addDocument(doc: StoredDocument): void {
  documents.push(doc);
}
export function softDeleteDocument(id: string): StoredDocument | undefined {
  const doc = getDocument(id);
  if (!doc) return undefined;
  doc.deleted_at = new Date().toISOString();
  return doc;
}

// --- policies ---
let policies: Policy[] = clone(fixtures.policies);

export function listPolicies(): Policy[] {
  return policies;
}
export function getPolicy(id: string): Policy | undefined {
  return policies.find((p) => p.id === id);
}
export function addPolicy(policy: Policy): void {
  policies.push(policy);
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
let claims: Claim[] = clone(fixtures.claims);

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
  return { ok: true, claim };
}

export function documentsForClaim(claimId: string): StoredDocument[] {
  return listDocuments().filter((d) => d.claim_id === claimId);
}

// --- jobs ---
interface JobRecord {
  job: Job<unknown>;
  createdAt: number;
  durationMs: number;
  resultFactory: () => unknown;
  cachedResult?: unknown;
}

const jobs = new Map<string, JobRecord>();

const JOB_STEPS: Record<JobKind, string[]> = {
  parse_document: ["classifying_pages", "extracting_tables", "structuring_coverage_profile"],
  answer_question: ["retrieving_clauses", "reranking", "generating_answer"],
  generate_grievance_draft: ["assembling_evidence", "drafting_paragraphs", "verifying_citations"],
};

export function createJob(kind: JobKind, durationMsRange: [number, number], resultFactory: () => unknown): Job<unknown> {
  const job_id = genId("job");
  const durationMs = durationMsRange[0] + Math.random() * (durationMsRange[1] - durationMsRange[0]);
  const job: Job<unknown> = { job_id, kind, status: "queued", progress: null, result: null, error: null };
  jobs.set(job_id, { job, createdAt: Date.now(), durationMs, resultFactory });
  return job;
}

export function getJob(jobId: string): Job<unknown> | undefined {
  const record = jobs.get(jobId);
  if (!record) return undefined;

  const elapsed = Date.now() - record.createdAt;
  if (elapsed >= record.durationMs) {
    if (record.cachedResult === undefined) {
      record.cachedResult = record.resultFactory();
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
const idempotencyStore = new Map<string, { status: number; body: JsonBodyType }>();

export function getIdempotentResponse(key: string): { status: number; body: JsonBodyType } | undefined {
  return idempotencyStore.get(key);
}
export function storeIdempotentResponse(key: string, status: number, body: JsonBodyType): void {
  idempotencyStore.set(key, { status, body });
}

export function resetDb(): void {
  documents = clone(fixtures.documents);
  policies = clone(fixtures.policies);
  claims = clone(fixtures.claims);
  jobs.clear();
  idempotencyStore.clear();
}
