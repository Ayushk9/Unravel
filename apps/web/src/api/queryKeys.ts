/**
 * Centralised TanStack Query key factory. New resource keys are added here as
 * their endpoint module is built — see src/api/endpoints/*.
 */
export const queryKeys = {
  health: () => ["health"] as const,

  documents: {
    all: () => ["documents"] as const,
    list: (cursor: string | null) => ["documents", "list", cursor] as const,
    detail: (id: string) => ["documents", "detail", id] as const,
    file: (id: string) => ["documents", "file", id] as const,
    byClaim: (claimId: string) => ["documents", "byClaim", claimId] as const,
  },
  policies: {
    all: () => ["policies"] as const,
    list: () => ["policies", "list"] as const,
    detail: (id: string) => ["policies", "detail", id] as const,
  },
  members: {
    list: () => ["members", "list"] as const,
  },
  claims: {
    all: () => ["claims"] as const,
    list: () => ["claims", "list"] as const,
    detail: (id: string) => ["claims", "detail", id] as const,
    eligibility: (id: string) => ["claims", "detail", id, "eligibility"] as const,
    completeness: (id: string) => ["claims", "detail", id, "completeness"] as const,
    billValidation: (id: string) => ["claims", "detail", id, "bill-validation"] as const,
  },
  alerts: {
    list: () => ["alerts", "list"] as const,
  },
  ombudsmanAwards: {
    list: (cursor: string | null) => ["ombudsman-awards", "list", cursor] as const,
  },
  insurerBenchmarks: {
    list: () => ["insurer-benchmarks", "list"] as const,
  },
  jobs: {
    detail: (jobId: string) => ["jobs", "detail", jobId] as const,
  },
};
