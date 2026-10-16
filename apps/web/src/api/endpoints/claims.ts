import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import type { ClaimCreateRequest, ClaimEventRequest, ClaimFactsRequest, GrievanceDraftRequest } from "@/api/types";
import { apiFetch } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import {
  billValidationReportSchema,
  claimSchema,
  completenessReportSchema,
  eligibilityAssessmentSchema,
  jobAcceptedSchema,
} from "@/api/schemas";

const claimsListSchema = z.array(claimSchema);

/**
 * Unpaginated. API_DECISIONS.md §5 doesn't actually list "claims" in either
 * pagination table (only documents/claim-events/ombudsman-awards are
 * paginated; policies/members/alerts/benchmarks explicitly aren't) — a real
 * gap, not a documented decision. Treated as unpaginated by the same
 * reasoning the ratified table uses for policies/alerts: a household's
 * claims are bounded, unlike the event log inside each one. Flagged in
 * DECISIONS.md.
 */
export function useClaims() {
  return useQuery({
    queryKey: queryKeys.claims.list(),
    queryFn: () => apiFetch(`/claims`, { schema: claimsListSchema }),
  });
}

export function useClaim(id: string | null) {
  return useQuery({
    queryKey: queryKeys.claims.detail(id ?? "none"),
    queryFn: () => apiFetch(`/claims/${id}`, { schema: claimSchema }),
    enabled: id !== null,
  });
}

export function useCreateClaim() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ClaimCreateRequest) => apiFetch(`/claims`, { method: "POST", body, schema: claimSchema }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.claims.all() });
    },
  });
}

/** D-16: the client only ever appends events — it never sets current_state directly. A 409 carries the allowed next states in ApiError.fieldErrors. */
export function useAppendClaimEvent(claimId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ClaimEventRequest) => apiFetch(`/claims/${claimId}/events`, { method: "POST", body, schema: claimSchema }),
    onSuccess: (claim) => {
      queryClient.setQueryData(queryKeys.claims.detail(claimId), claim);
    },
  });
}

/** D-37: PUT replaces every fact at once. The eligibility assessment reads them, so it is refetched. */
export function useSaveClaimFacts(claimId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ClaimFactsRequest) => apiFetch(`/claims/${claimId}/facts`, { method: "PUT", body, schema: claimSchema }),
    onSuccess: (claim) => {
      queryClient.setQueryData(queryKeys.claims.detail(claimId), claim);
      void queryClient.invalidateQueries({ queryKey: queryKeys.claims.eligibility(claimId) });
    },
  });
}

/**
 * Eligibility/completeness/bill-validation are POST on the wire (D-07) but
 * behave as reads the claim workspace's tabs auto-load on open, so they're
 * modelled as queries here rather than mutations — TanStack Query doesn't
 * care which HTTP verb queryFn uses.
 */
export function useEligibility(claimId: string | null) {
  return useQuery({
    queryKey: queryKeys.claims.eligibility(claimId ?? "none"),
    queryFn: () => apiFetch(`/claims/${claimId}/eligibility`, { method: "POST", schema: eligibilityAssessmentSchema }),
    enabled: claimId !== null,
  });
}

/** `poll` (Phase 4): the claim wizard's Documents step re-derives completeness as uploads finish parsing, so it opts into a light poll rather than requiring a manual refetch after every upload. */
export function useCompleteness(claimId: string | null, { poll = false }: { poll?: boolean } = {}) {
  return useQuery({
    queryKey: queryKeys.claims.completeness(claimId ?? "none"),
    queryFn: () => apiFetch(`/claims/${claimId}/completeness`, { method: "POST", schema: completenessReportSchema }),
    enabled: claimId !== null,
    refetchInterval: poll ? 2000 : false,
  });
}

/** 409s if the bill document isn't parsed yet — see ApiError.code === "bill_not_parsed". */
export function useBillValidation(claimId: string | null) {
  return useQuery({
    queryKey: queryKeys.claims.billValidation(claimId ?? "none"),
    queryFn: () => apiFetch(`/claims/${claimId}/bill-validation`, { method: "POST", schema: billValidationReportSchema }),
    enabled: claimId !== null,
    retry: false, // a 409 here is a normal "not ready yet" state, not a transient failure to retry
  });
}

export interface RequestGrievanceDraftInput extends GrievanceDraftRequest {
  idempotencyKey: string;
}

/** D-07 job + D-13 idempotency key required. */
export function useRequestGrievanceDraft(claimId: string) {
  return useMutation({
    mutationFn: ({ idempotencyKey, ...body }: RequestGrievanceDraftInput) =>
      apiFetch(`/claims/${claimId}/grievance-drafts`, { method: "POST", body, idempotencyKey, schema: jobAcceptedSchema }),
  });
}
