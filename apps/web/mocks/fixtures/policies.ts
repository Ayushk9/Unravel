import type { CoverageProfile, Extracted, Policy, Provenance } from "@/api/types";
import { ids } from "./ids";
import { insurerById } from "./insurers";
import { memberById } from "./members";

function prov(documentId: string, page: number, snippet: string): Provenance {
  return { document_id: documentId, page, bbox: null, snippet };
}

function confirmed<T>(value: T, confidence: Extracted<T>["confidence"], provenance: Provenance | null): Extracted<T> {
  return { value, confidence, provenance, user_confirmed: true };
}

function unconfirmed<T>(
  value: T,
  confidence: Extracted<T>["confidence"],
  provenance: Provenance | null,
): Extracted<T> {
  return { value, confidence, provenance, user_confirmed: false };
}

// --- Employer group floater: Kavach Corporate Health Shield ---
const groupCoverage: CoverageProfile = {
  policy_id: ids.policy.group,
  sum_insured: confirmed(500_000_00, "high", prov(ids.document.groupSchedule, 1, "Sum Insured: Rs. 5,00,000 (Family Floater)")),
  co_pay_percent: confirmed(0, "high", prov(ids.document.groupSchedule, 2, "Co-payment: Nil")),
  sub_limits: [
    {
      category: "room_rent",
      label: "Room rent",
      cap_amount: confirmed(4_000_00, "high", prov(ids.document.groupSchedule, 2, "Room Rent: Rs. 4,000 per day")),
      cap_basis: "per_day",
      percent_value: null,
    },
  ],
  waiting_periods: [
    {
      kind: "initial",
      months: confirmed(1, "high", prov(ids.document.groupSchedule, 3, "Initial waiting period: 30 days")),
      applies_to: null,
      starts_on: "2026-04-01",
      expires_on: "2026-05-01",
    },
    {
      // Continuously renewed since 2024-09-05 — this clock runs from that
      // date, not the current term's start_date, same logic as the retail
      // policy's PED waiting period below.
      kind: "disease_specific",
      months: confirmed(24, "high", prov(ids.document.groupSchedule, 3, "Cataract surgery: 24-month waiting period")),
      applies_to: "cataract surgery",
      starts_on: "2024-09-05",
      expires_on: "2026-09-05",
    },
  ],
  exclusions: [
    confirmed(
      "Maternity expenses, including childbirth and related complications, are not covered under this policy.",
      "high",
      prov(ids.document.groupSchedule, 4, "Exclusion: Maternity and childbirth expenses"),
    ),
  ],
  intimation_deadline_hours: confirmed(48, "high", prov(ids.document.groupSchedule, 5, "Claims must be intimated within 48 hours")),
  extraction_completeness: 0.95,
};

export const groupPolicy: Policy = {
  id: ids.policy.group,
  insurer: insurerById(ids.insurer.group),
  policy_number: "KHA/GRP/2026/0098231",
  product_name: "Kavach Corporate Health Shield",
  policy_type: "group_employer",
  start_date: "2026-04-01",
  end_date: "2027-03-31",
  members: [memberById(ids.member.self), memberById(ids.member.spouse), memberById(ids.member.child), memberById(ids.member.parent)],
  coverage_profile: groupCoverage,
  source_document_id: ids.document.groupSchedule,
};

// --- Retail individual: Suraksha Complete Health Plan ---
// Continuously renewed since original inception 2023-04-01 — waiting periods
// count from inception, not from the current term's start_date. This is what
// makes the PED waiting period (expires 2027-04-01) still relevant to a claim
// admitted in the current 2026-04-01..2027-03-31 term.
const ORIGINAL_INCEPTION = "2023-04-01";

const retailCoverage: CoverageProfile = {
  policy_id: ids.policy.retail,
  sum_insured: confirmed(10_00_000_00, "high", prov(ids.document.retailSchedule, 1, "Sum Insured: Rs. 10,00,000")),
  co_pay_percent: unconfirmed(10, "medium", prov(ids.document.retailSchedule, 1, "Co-payment: 10% of admissible claim amount")),
  sub_limits: [
    {
      category: "room_rent",
      label: "Room rent",
      // Low confidence, unconfirmed — this exact figure (500000 paise, per_day)
      // is deliberately the same number the bill-validation flag and the
      // room_rent_below_market alert both cite. See DECISIONS.md.
      cap_amount: unconfirmed(
        5_000_00,
        "low",
        prov(ids.document.retailWording, 14, "...room rent shall not exceed Rs. 5,000 per day, beyond which..."),
      ),
      cap_basis: "per_day",
      percent_value: null,
    },
  ],
  waiting_periods: [
    {
      kind: "initial",
      months: confirmed(1, "high", prov(ids.document.retailWording, 6, "Initial waiting period of 30 days from inception")),
      applies_to: null,
      starts_on: ORIGINAL_INCEPTION,
      expires_on: "2023-05-01",
    },
    {
      kind: "pre_existing",
      months: confirmed(48, "high", prov(ids.document.retailWording, 7, "Pre-existing diseases are covered after 48 months of continuous coverage")),
      applies_to: null,
      starts_on: ORIGINAL_INCEPTION,
      expires_on: "2027-04-01",
    },
    {
      kind: "maternity",
      months: confirmed(24, "high", prov(ids.document.retailWording, 9, "Maternity benefit becomes available after 24 months of continuous coverage")),
      applies_to: null,
      starts_on: ORIGINAL_INCEPTION,
      expires_on: "2025-04-01",
    },
  ],
  exclusions: [
    confirmed(
      "Cosmetic surgery is excluded unless medically necessitated by an accident covered under this policy.",
      "high",
      prov(ids.document.retailWording, 18, "Exclusion 9.4: Cosmetic surgery"),
    ),
    confirmed(
      "Dental treatment is excluded unless it requires hospitalisation due to an accident.",
      "high",
      prov(ids.document.retailWording, 18, "Exclusion 9.6: Dental treatment"),
    ),
  ],
  intimation_deadline_hours: unconfirmed(48, "medium", prov(ids.document.retailWording, 22, "Intimation of claim within 48 hours of admission")),
  extraction_completeness: 0.82,
};

export const retailPolicy: Policy = {
  id: ids.policy.retail,
  insurer: insurerById(ids.insurer.retail),
  policy_number: "SGI/IND/2023/00456781",
  product_name: "Suraksha Complete Health Plan",
  policy_type: "individual",
  start_date: "2026-04-01",
  end_date: "2027-03-31",
  members: [memberById(ids.member.self)],
  coverage_profile: retailCoverage,
  source_document_id: ids.document.retailSchedule,
};

export const policies: Policy[] = [groupPolicy, retailPolicy];

export function policyById(id: string): Policy | undefined {
  return policies.find((p) => p.id === id);
}
