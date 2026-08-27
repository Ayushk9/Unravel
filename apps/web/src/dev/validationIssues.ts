/**
 * Dev-only record of live-route responses that failed zod validation (Task 2).
 * Pure state, same shape as scenarios.ts — no MSW/fetch concerns here, safe
 * for DevToolbar.tsx to import directly. client.ts writes to this whenever a
 * response from an allowlisted/live route doesn't match its schema; it does
 * NOT throw in that case (fixture-drift-on-mock still throws, by design —
 * this is the live-path-only relief valve), so this is the only place that
 * information surfaces without a red error screen.
 */
export interface ValidationIssue {
  method: string;
  path: string;
  /** zod's issue list, already a plain serializable shape. */
  issues: { path: (string | number)[]; message: string }[];
  at: number;
}

const MAX_KEPT = 20;

let issues: ValidationIssue[] = [];
const subscribers = new Set<(issues: ValidationIssue[]) => void>();

export function recordValidationIssue(issue: Omit<ValidationIssue, "at">): void {
  issues = [...issues, { ...issue, at: Date.now() }].slice(-MAX_KEPT);
  subscribers.forEach((cb) => cb(issues));
}

export function getValidationIssues(): ValidationIssue[] {
  return issues;
}

export function clearValidationIssues(): void {
  issues = [];
  subscribers.forEach((cb) => cb(issues));
}

export function subscribeValidationIssues(cb: (issues: ValidationIssue[]) => void): () => void {
  subscribers.add(cb);
  return () => subscribers.delete(cb);
}
