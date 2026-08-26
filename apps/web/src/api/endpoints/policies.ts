import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import type { FieldCorrectionRequest, PolicyCreateRequest, QuestionRequest } from "@/api/types";
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

/** D-15: targeted PATCH, never a whole-profile PUT. fieldPath is dotted, e.g. "sub_limits.room_rent.cap_amount". */
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
