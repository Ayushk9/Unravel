import type { OmbudsmanAward } from "@/api/types";

/**
 * Fully fictional award records — case references, summaries, and outcomes
 * are invented for the demo, matched against fictional insurers (see
 * insurers.ts). external_url is null on every one deliberately: pairing
 * fabricated case data with a link to a real regulator domain would imply a
 * verifiability these records don't have.
 */
export const ombudsmanAwards: OmbudsmanAward[] = [
  {
    id: "award-01",
    case_reference: "GIC/2025/00142",
    insurer_name: "Suraksha General Insurance",
    decided_on: "2025-11-20",
    denial_ground: "Pre-existing disease non-disclosure",
    outcome: "overturned",
    summary:
      "Insurer denied the claim alleging the condition pre-existed the policy but produced no medical evidence beyond the discharge summary. The Ombudsman held that continuous, unbroken renewal counts toward the waiting period from original inception, and that the insurer's own underwriting file showed no adverse remark at renewal.",
    external_url: null,
  },
  {
    id: "award-02",
    case_reference: "GIC/2025/00298",
    insurer_name: "Kavach Health Assurance",
    decided_on: "2025-08-05",
    denial_ground: "Pre-existing disease non-disclosure",
    outcome: "overturned",
    summary:
      "The insurer's investigator relied on a single unclear line in an old prescription to infer a pre-existing condition. The Ombudsman found the inference speculative and directed settlement in full, noting the insurer bears the burden of proof for a non-disclosure denial.",
    external_url: null,
  },
  {
    id: "award-03",
    case_reference: "GIC/2024/00871",
    insurer_name: "Nirvaan Health Insurance",
    decided_on: "2024-12-12",
    denial_ground: "Pre-existing disease non-disclosure",
    outcome: "upheld",
    summary:
      "Medical records from two years before the policy's inception documented the same diagnosis under active treatment, and the proposal form's health declaration was silent on it. The Ombudsman upheld the denial for non-disclosure of a known pre-existing condition.",
    external_url: null,
  },
  {
    id: "award-04",
    case_reference: "GIC/2025/00405",
    insurer_name: "Bharosa General Insurance",
    decided_on: "2025-05-30",
    denial_ground: "Room rent sub-limit — proportionate deduction dispute",
    outcome: "partially_allowed",
    summary:
      "The insurer applied a proportionate deduction across the entire bill after the room chosen exceeded the policy's per-day cap. The Ombudsman held the deduction methodology was correctly applied to room-rent-linked charges but not to fixed-fee items like the surgeon's fee, and revised the settlement upward.",
    external_url: null,
  },
  {
    id: "award-05",
    case_reference: "GIC/2024/01120",
    insurer_name: "Rakshak General Insurance",
    decided_on: "2024-09-18",
    denial_ground: "Delayed intimation",
    outcome: "overturned",
    summary:
      "Claim was denied solely for intimation four days after the policy's stated window during an emergency admission. The Ombudsman held a short delay during genuine medical emergency, with no prejudice to the insurer's ability to investigate, is not sufficient grounds for outright denial.",
    external_url: null,
  },
  {
    id: "award-06",
    case_reference: "GIC/2025/00033",
    insurer_name: "Vishwas General Insurance",
    decided_on: "2025-02-14",
    denial_ground: "Non-payable consumables deduction dispute",
    outcome: "upheld",
    summary:
      "Policyholder disputed deductions for gloves, syringes, and other consumables as arbitrary. The Ombudsman found the deductions matched the insurer's published non-payables list, attached to the policy wording, and upheld the settlement as calculated.",
    external_url: null,
  },
];

export function ombudsmanAwardsByDenialGroundKeyword(keyword: string): OmbudsmanAward[] {
  const needle = keyword.toLowerCase();
  return ombudsmanAwards.filter((award) => award.denial_ground.toLowerCase().includes(needle));
}
