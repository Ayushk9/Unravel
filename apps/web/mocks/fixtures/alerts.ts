import type { Alert } from "@/api/types";
import { ids } from "./ids";
import { prov } from "./policies";

/**
 * One alert per real Alert.kind value (five, not the brief's stated "four" —
 * the type has five kinds plus the D-06 "other" escape hatch; see
 * DECISIONS.md). Every figure here is consistent with the policy fixtures:
 * the room-rent alert cites the same ₹5,000/day cap as the retail policy and
 * the bill-validation flag, and the waiting-period alert's "11 days" is real
 * arithmetic against the group policy's cataract waiting period, not a
 * hardcoded string — see policies.ts.
 */
export const alerts: Alert[] = [
  {
    id: "alert-room-rent",
    policy_id: ids.policy.retail,
    kind: "room_rent_below_market",
    severity: "warning",
    title: "Your room rent choice may cost more than you think",
    explanation:
      "Your Suraksha Complete Health Plan caps room rent at ₹5,000/day. Choosing a room above that cap can trigger a proportionate deduction across your whole bill, not just the room charge.",
    suggested_action: "Ask the hospital for a room at or below ₹5,000/day, or budget for the difference.",
    reference_source: "Estimated from typical private-ward rates in metro hospitals — not insurer-published data.",
    triggers_on: null,
    verified: false,
    provenance: prov(ids.document.retailWording, 14, "...room rent shall not exceed Rs. 5,000 per day, beyond which..."),
  },
  {
    id: "alert-waiting-period",
    policy_id: ids.policy.group,
    kind: "waiting_period_expiring",
    severity: "info",
    title: "Cataract surgery waiting period ends in 11 days",
    explanation:
      "Your Kavach Corporate Health Shield's 24-month waiting period for cataract surgery, running since 5 Sep 2024, ends 5 Sep 2026.",
    suggested_action: null,
    reference_source: null,
    triggers_on: "2026-09-05",
    verified: true,
    provenance: prov(ids.document.groupSchedule, 3, "Cataract surgery: 24-month waiting period"),
  },
  {
    id: "alert-renewal",
    policy_id: ids.policy.retail,
    kind: "renewal_due",
    severity: "info",
    title: "Suraksha Complete Health Plan is due for renewal",
    explanation: "Your current policy term ends 31 Mar 2027. Renewing on time keeps your waiting-period clock unbroken.",
    suggested_action: "Set a reminder for early March.",
    reference_source: null,
    triggers_on: "2027-03-31",
    verified: true,
    provenance: null,
  },
  {
    id: "alert-no-maternity",
    policy_id: ids.policy.group,
    kind: "no_maternity_cover",
    severity: "warning",
    title: "No maternity cover on your Kavach Corporate Health Shield",
    explanation: "Maternity expenses, including childbirth and related complications, are excluded under this policy.",
    suggested_action: "Consider a maternity rider or a different plan if you're planning a family.",
    reference_source: null,
    triggers_on: null,
    verified: true,
    provenance: null,
  },
  {
    id: "alert-low-sum-insured",
    policy_id: ids.policy.group,
    kind: "low_sum_insured",
    severity: "info",
    title: "₹5,00,000 may not cover a major hospitalisation",
    explanation: "Your Kavach Corporate Health Shield's ₹5,00,000 sum insured is below what a major surgery in a metro hospital often costs.",
    suggested_action: "Consider a top-up policy for additional cover.",
    reference_source: "Estimated from average metro hospitalisation costs — not insurer-published data.",
    triggers_on: null,
    verified: false,
    provenance: prov(ids.document.groupSchedule, 1, "Sum Insured: Rs. 5,00,000 (Family Floater)"),
  },
];
