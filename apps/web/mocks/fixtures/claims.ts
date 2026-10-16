import type { Claim, ClaimEvent } from "@/api/types";
import { ids } from "./ids";
import { deniedClaimBillTotalBilled } from "./bill";

/**
 * `deadlines` and `current_state` below are placeholders overwritten at
 * request time by the claims handler, which recomputes both from `events`
 * on every read (D-16, D-17) — never trust a stored value. Kept here only so
 * the fixture type-checks as a complete Claim.
 */

const deniedEvents: ClaimEvent[] = [
  {
    id: "event-denied-01",
    claim_id: ids.claim.denied,
    from_state: null,
    to_state: "intimated",
    occurred_at: "2026-07-06T10:00:00+05:30",
    note: "Claim intimated via app",
    source: "user",
  },
  {
    id: "event-denied-02",
    claim_id: ids.claim.denied,
    from_state: "intimated",
    to_state: "documents_submitted",
    occurred_at: "2026-07-12T14:10:00+05:30",
    note: "Discharge summary and itemised bill uploaded",
    source: "user",
  },
  {
    id: "event-denied-03",
    claim_id: ids.claim.denied,
    from_state: "documents_submitted",
    to_state: "under_review",
    occurred_at: "2026-07-14T09:00:00+05:30",
    note: "Insurer acknowledged receipt and began review",
    source: "system",
  },
  {
    id: "event-denied-04",
    claim_id: ids.claim.denied,
    from_state: "under_review",
    to_state: "denied",
    occurred_at: "2026-08-10T11:00:00+05:30",
    note: "Denied — condition assessed as pre-existing to policy inception, per medical records reviewed",
    source: "insurer_letter",
  },
];

const underReviewEvents: ClaimEvent[] = [
  {
    id: "event-under-review-01",
    claim_id: ids.claim.underReview,
    from_state: null,
    to_state: "intimated",
    occurred_at: "2026-08-15T08:30:00+05:30",
    note: "Claim intimated via app",
    source: "user",
  },
  {
    id: "event-under-review-02",
    claim_id: ids.claim.underReview,
    from_state: "intimated",
    to_state: "documents_submitted",
    occurred_at: "2026-08-16T10:00:00+05:30",
    note: "Discharge summary uploaded",
    source: "user",
  },
  {
    id: "event-under-review-03",
    claim_id: ids.claim.underReview,
    from_state: "documents_submitted",
    to_state: "under_review",
    occurred_at: "2026-08-17T09:15:00+05:30",
    note: "Insurer began review",
    source: "system",
  },
];

const settledEvents: ClaimEvent[] = [
  {
    id: "event-settled-01",
    claim_id: ids.claim.settled,
    from_state: null,
    to_state: "intimated",
    occurred_at: "2026-02-03T09:00:00+05:30",
    note: "Claim intimated ahead of planned admission",
    source: "user",
  },
  {
    id: "event-settled-02",
    claim_id: ids.claim.settled,
    from_state: "intimated",
    to_state: "documents_submitted",
    occurred_at: "2026-02-09T11:00:00+05:30",
    note: "Discharge summary and itemised bill uploaded",
    source: "user",
  },
  {
    id: "event-settled-03",
    claim_id: ids.claim.settled,
    from_state: "documents_submitted",
    to_state: "under_review",
    occurred_at: "2026-02-10T09:00:00+05:30",
    note: "Insurer began review",
    source: "system",
  },
  {
    id: "event-settled-04",
    claim_id: ids.claim.settled,
    from_state: "under_review",
    to_state: "approved",
    occurred_at: "2026-02-20T10:00:00+05:30",
    note: "Approved with standard deductions",
    source: "insurer_letter",
  },
  {
    id: "event-settled-05",
    claim_id: ids.claim.settled,
    from_state: "approved",
    to_state: "resolved",
    occurred_at: "2026-02-25T12:00:00+05:30",
    note: "Settlement paid to the bank account on file",
    source: "system",
  },
];

export const NO_FACTS: Claim["facts"] = {
  diagnosis: null,
  condition_is_pre_existing: null,
  first_diagnosed_on: null,
  matched_waiting_periods: null,
  matched_exclusions: null,
  planned_room_rent_per_day: null,
};

export const deniedClaim: Claim = {
  id: ids.claim.denied,
  policy_id: ids.policy.retail,
  member_id: ids.member.self,
  claim_type: "reimbursement",
  admission_type: "emergency",
  hospital_name: "Manipal Hospital, Bengaluru",
  admitted_on: "2026-07-05",
  discharged_on: "2026-07-10",
  claimed_amount: deniedClaimBillTotalBilled,
  settled_amount: null,
  current_state: "denied",
  events: deniedEvents,
  deadlines: [],
  omitted_deadlines: [],
  facts: {
    diagnosis: "Complications of type 2 diabetes",
    condition_is_pre_existing: true,
    first_diagnosed_on: "2022-11-05",
    matched_waiting_periods: [],
    matched_exclusions: [],
    planned_room_rent_per_day: null,
  },
};

export const underReviewClaim: Claim = {
  id: ids.claim.underReview,
  policy_id: ids.policy.group,
  member_id: ids.member.spouse,
  claim_type: "reimbursement",
  admission_type: "emergency",
  hospital_name: "Fortis Hospital, Bengaluru",
  admitted_on: "2026-08-14",
  discharged_on: "2026-08-17",
  claimed_amount: 85_000_00,
  settled_amount: null,
  current_state: "under_review",
  events: underReviewEvents,
  deadlines: [],
  omitted_deadlines: [],
  facts: NO_FACTS,
};

export const settledClaim: Claim = {
  id: ids.claim.settled,
  policy_id: ids.policy.retail,
  member_id: ids.member.self,
  claim_type: "reimbursement",
  admission_type: "planned",
  hospital_name: "Apollo Hospital, Chennai",
  admitted_on: "2026-02-05",
  discharged_on: "2026-02-08",
  claimed_amount: 42_000_00,
  settled_amount: 39_000_00,
  current_state: "resolved",
  events: settledEvents,
  deadlines: [],
  omitted_deadlines: [],
  facts: NO_FACTS,
};

export const claims: Claim[] = [deniedClaim, underReviewClaim, settledClaim];

export function claimById(id: string): Claim | undefined {
  return claims.find((c) => c.id === id);
}
