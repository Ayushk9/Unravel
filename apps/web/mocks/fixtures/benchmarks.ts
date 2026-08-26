import type { InsurerBenchmark } from "@/api/types";
import { ids } from "./ids";
import { insurerById } from "./insurers";

const PLACEHOLDER_SOURCE = {
  name: "IRDAI Annual Report FY2024-25 (fixture placeholder — unverified)",
  published_on: "2025-09-30",
  url: "",
};

/**
 * 10 insurers. Three have avg_turnaround_days: null on purpose — patchy
 * regulator-published turnaround data is the norm, not the exception, and
 * <InsurerBenchmark> must render "Not reported" for it rather than 0.
 */
export const benchmarks: InsurerBenchmark[] = [
  {
    insurer: insurerById(ids.insurer.retail),
    period: "FY2024-25",
    claim_settlement_ratio: 0.94,
    incurred_claims_ratio: 0.68,
    avg_turnaround_days: 12,
    complaints_per_10k_policies: 3.2,
    ombudsman_cases_lost_share: 0.31,
    source: PLACEHOLDER_SOURCE,
  },
  {
    insurer: insurerById(ids.insurer.group),
    period: "FY2024-25",
    claim_settlement_ratio: 0.91,
    incurred_claims_ratio: 0.71,
    avg_turnaround_days: 15,
    complaints_per_10k_policies: 2.8,
    ombudsman_cases_lost_share: 0.24,
    source: PLACEHOLDER_SOURCE,
  },
  {
    insurer: insurerById(ids.insurer.bench3),
    period: "FY2024-25",
    claim_settlement_ratio: 0.88,
    incurred_claims_ratio: 0.74,
    avg_turnaround_days: null,
    complaints_per_10k_policies: 4.1,
    ombudsman_cases_lost_share: 0.4,
    source: PLACEHOLDER_SOURCE,
  },
  {
    insurer: insurerById(ids.insurer.bench4),
    period: "FY2024-25",
    claim_settlement_ratio: 0.96,
    incurred_claims_ratio: 0.62,
    avg_turnaround_days: 9,
    complaints_per_10k_policies: 1.9,
    ombudsman_cases_lost_share: 0.18,
    source: PLACEHOLDER_SOURCE,
  },
  {
    insurer: insurerById(ids.insurer.bench5),
    period: "FY2024-25",
    claim_settlement_ratio: 0.85,
    incurred_claims_ratio: 0.79,
    avg_turnaround_days: null,
    complaints_per_10k_policies: 5.6,
    ombudsman_cases_lost_share: 0.52,
    source: PLACEHOLDER_SOURCE,
  },
  {
    insurer: insurerById(ids.insurer.bench6),
    period: "FY2024-25",
    claim_settlement_ratio: 0.9,
    incurred_claims_ratio: 0.7,
    avg_turnaround_days: 18,
    complaints_per_10k_policies: 3.5,
    ombudsman_cases_lost_share: 0.29,
    source: PLACEHOLDER_SOURCE,
  },
  {
    insurer: insurerById(ids.insurer.bench7),
    period: "FY2024-25",
    claim_settlement_ratio: 0.93,
    incurred_claims_ratio: 0.65,
    avg_turnaround_days: null,
    complaints_per_10k_policies: 2.4,
    ombudsman_cases_lost_share: null,
    source: PLACEHOLDER_SOURCE,
  },
  {
    insurer: insurerById(ids.insurer.bench8),
    period: "FY2024-25",
    claim_settlement_ratio: 0.82,
    incurred_claims_ratio: 0.83,
    avg_turnaround_days: 24,
    complaints_per_10k_policies: 6.8,
    ombudsman_cases_lost_share: 0.61,
    source: PLACEHOLDER_SOURCE,
  },
  {
    insurer: insurerById(ids.insurer.bench9),
    period: "FY2024-25",
    claim_settlement_ratio: 0.97,
    incurred_claims_ratio: 0.59,
    avg_turnaround_days: 7,
    complaints_per_10k_policies: 1.4,
    ombudsman_cases_lost_share: 0.12,
    source: PLACEHOLDER_SOURCE,
  },
  {
    insurer: insurerById(ids.insurer.bench10),
    period: "FY2024-25",
    claim_settlement_ratio: null,
    incurred_claims_ratio: 0.77,
    avg_turnaround_days: 20,
    complaints_per_10k_policies: 4.7,
    ombudsman_cases_lost_share: 0.38,
    source: PLACEHOLDER_SOURCE,
  },
];
