import type { Claim, Deadline } from "@/api/types";
import { PLACEHOLDER_OMBUDSMAN_FILING_WINDOW_DAYS, urgencyForDaysRemaining } from "./fixtures/reference-data";
import { addDaysToIso, daysRemaining, formatDMY } from "./dateMath";
import { getScenarios } from "./scenarios";

/**
 * D-17: deadlines are computed here, at request time, from the claim's own
 * event log — never stored statically. That's what keeps "the event log
 * dates actually produce the deadlines returned" true forever, not just on
 * the day this fixture was written.
 */
export function computeDeadlines(claim: Claim): Deadline[] {
  const deadlines: Deadline[] = [];

  const deniedEvent = [...claim.events].reverse().find((e) => e.to_state === "denied");
  if (deniedEvent && claim.current_state === "denied") {
    const dueAt = addDaysToIso(deniedEvent.occurred_at, PLACEHOLDER_OMBUDSMAN_FILING_WINDOW_DAYS);
    const remaining = daysRemaining(dueAt);
    deadlines.push({
      id: `deadline-ombudsman-filing-${claim.id}`,
      label: "Ombudsman filing window",
      due_at: dueAt,
      days_remaining: remaining,
      basis: `${PLACEHOLDER_OMBUDSMAN_FILING_WINDOW_DAYS} days from the denial on ${formatDMY(deniedEvent.occurred_at.slice(0, 10))} — placeholder figure, needs verification (see DECISIONS.md)`,
      urgency: urgencyForDaysRemaining(remaining),
      source: null,
      verified: false,
    });
  }

  const scenarios = getScenarios();
  if (scenarios.forceExpiredDeadline) {
    const expiredDueAt = addDaysToIso(new Date().toISOString(), -10);
    deadlines.push({
      id: `deadline-forced-expired-${claim.id}`,
      label: "Ombudsman filing window (dev toolbar: forced expired)",
      due_at: expiredDueAt,
      days_remaining: daysRemaining(expiredDueAt),
      basis: "Forced into the expired state from the dev toolbar.",
      urgency: "expired",
      source: null,
      verified: false,
    });
  }

  return deadlines;
}
