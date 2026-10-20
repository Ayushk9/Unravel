import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import type { FieldCorrectionRequest, PolicyCreateRequest, PolicyUpdateRequest, QuestionRequest } from "@/api/types";
import { apiFetch } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import { jobAcceptedSchema, policySchema } from "@/api/schemas";

const policiesListSchema = z.array(policySchema);

/** Unpaginated — a household has under ten policies (API_DECISIONS.md §5). */
export function usePolicies() {
  return useQuery({
    queryKey: queryKeys.policies.list(),
    queryFn: () => apiFetch(`/policies`, { schema: policiesListSchema }),
  });
}

export function usePolicy(id: string | null) {
  return useQuery({
    queryKey: queryKeys.policies.detail(id ?? "none"),
    queryFn: () => apiFetch(`/policies/${id}`, { schema: policySchema }),
    enabled: id !== null,
  });
}

export function useCreatePolicy() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: PolicyCreateRequest) => apiFetch(`/policies`, { method: "POST", body, schema: policySchema }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.policies.all() });
    },
  });
}

/**
 * D-39: set the dates from the policy schedule. Only the keys sent change; null clears one.
 * Alerts and every claim's eligibility depend on these dates, so both are refetched.
 */
/** D-39, D-46: the user's own entries from their schedule (identity and dates). Only the keys sent change. */
export function useUpdatePolicy(policyId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: PolicyUpdateRequest) => apiFetch(`/policies/${policyId}`, { method: "PATCH", body, schema: policySchema }),
    onSuccess: (policy) => {
      queryClient.setQueryData(queryKeys.policies.detail(policyId), policy);
      void queryClient.invalidateQueries({ queryKey: queryKeys.policies.list() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.alerts.list() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.claims.all() });
    },
  });
}

/**
 * D-15 / D-41: targeted PATCH, never a whole-profile PUT. fieldPath is dotted.
 * Rows in a list are addressed by position ("sub_limits.2.cap_amount"), which
 * always names exactly one row even when two share a category.
 */
export function useCorrectPolicyField(policyId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ fieldPath, ...body }: FieldCorrectionRequest & { fieldPath: string }) =>
      apiFetch(`/policies/${policyId}/coverage-profile/fields/${fieldPath}`, { method: "PATCH", body, schema: policySchema }),
    onSuccess: (policy) => {
      queryClient.setQueryData(queryKeys.policies.detail(policyId), policy);
    },
  });
}

/** D-07 job endpoint — grounded Q&A. Poll the result with useJobPolling + questionAnswerResultSchema. */
export function useAskQuestion(policyId: string) {
  return useMutation({
    mutationFn: (body: QuestionRequest) =>
      apiFetch(`/policies/${policyId}/questions`, { method: "POST", body, schema: jobAcceptedSchema }),
  });
}
