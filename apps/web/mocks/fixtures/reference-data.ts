/**
 * Regulatory figures used to compute deadlines and eligibility explanations
 * in the mock backend. NONE of these are verified against a primary source —
 * see /DECISIONS.md "Needs verification against primary source". Every value
 * here is an OBVIOUS placeholder, not a best guess dressed up as fact:
 * round, commented, and named so nobody mistakes it for a cited figure.
 *
 * This file plays the role a real backend's versioned reference-data table
 * would play (API_DECISIONS.md §8's closing rule) — it exists so the report
 * can point at one place to fix these later, and so no regulatory number is
 * hardcoded inside handler logic.
 */

export const PLACEHOLDER_OMBUDSMAN_FILING_WINDOW_DAYS = 30;
// PLACEHOLDER. API_DECISIONS.md §8 lists the real filing window (from date of
// repudiation) as unverified and load-bearing for Feature 6. Needs checking
// against the Insurance Ombudsman Rules as amended.

export const PLACEHOLDER_INSURER_SILENCE_ESCALATION_DAYS = 30;
// PLACEHOLDER. "Days of insurer silence before escalation is permitted" —
// unverified per API_DECISIONS.md §8.

export const PLACEHOLDER_OMBUDSMAN_AWARD_CEILING_PAISE = 30_00_000_00; // ₹30,00,000
// PLACEHOLDER, and a genuinely disputed figure — API_DECISIONS.md §8 notes
// sources conflict between ₹30 lakh and ₹50 lakh. Using the lower figure here
// only because a placeholder has to be some number; this is not a claim that
// ₹30L is the correct one.

/**
 * Deadline urgency bucketing. API_DECISIONS.md defines urgency as a computed
 * field but not its thresholds — this is a mock-only assumption, not a
 * contract commitment. A real backend is free to define its own.
 */
export function urgencyForDaysRemaining(daysRemaining: number): "critical" | "soon" | "normal" | "expired" {
  if (daysRemaining < 0) return "expired";
  if (daysRemaining <= 3) return "critical";
  if (daysRemaining <= 14) return "soon";
  return "normal";
}
