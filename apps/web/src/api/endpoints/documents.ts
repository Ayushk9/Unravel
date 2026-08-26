import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { DocumentType } from "@/api/types";
import { apiFetch } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import { collectionSchema, jobAcceptedSchema, storedDocumentSchema } from "@/api/schemas";

const documentsPageSchema = collectionSchema(storedDocumentSchema);

/** D-05 cursor pagination — GET /documents is one of only three paginated resources. */
export function useDocuments() {
  return useInfiniteQuery({
    queryKey: queryKeys.documents.list(null),
    queryFn: ({ pageParam }) => {
      const search = pageParam ? `?cursor=${encodeURIComponent(pageParam)}` : "";
      return apiFetch(`/documents${search}`, { schema: documentsPageSchema });
    },
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
  });
}

export function useDocument(id: string | null) {
  return useQuery({
    queryKey: queryKeys.documents.detail(id ?? "none"),
    queryFn: () => apiFetch(`/documents/${id}`, { schema: storedDocumentSchema }),
    enabled: id !== null,
  });
}

export interface UploadDocumentInput {
  file: File;
  claimId?: string | null;
  idempotencyKey: string;
}

/** D-07 job endpoint, D-13 idempotency key required — returns a job to poll with useJobPolling. */
export function useUploadDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ file, claimId, idempotencyKey }: UploadDocumentInput) => {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("claim_id", claimId ?? "");
      return apiFetch(`/documents`, {
        method: "POST",
        body: formData,
        idempotencyKey,
        schema: jobAcceptedSchema,
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.documents.all() });
    },
  });
}

/**
 * Phase 4 addition: `claim_id` is a Phase 2 filter query param on the same
 * paginated GET /documents endpoint (not a new endpoint) — see CONTRACTS.md
 * §2 and DECISIONS.md. A claim's own documents are few, so this fetches one
 * page rather than paginating properly, and polls while any of them are
 * still queued/parsing so the wizard's live document list (and, via the
 * caller re-triggering completeness, the completeness panel) update without
 * a manual refresh.
 */
export function useClaimDocuments(claimId: string | null) {
  return useQuery({
    queryKey: queryKeys.documents.byClaim(claimId ?? "none"),
    queryFn: () => apiFetch(`/documents?claim_id=${claimId}&limit=100`, { schema: documentsPageSchema }),
    enabled: claimId !== null,
    select: (page) => page.items,
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      const stillWorking = items.some((d) => d.parse_status === "queued" || d.parse_status === "parsing");
      return stillWorking ? 2000 : false;
    },
  });
}

/** Corrects a misclassified document type — editable dropdown in the claim wizard's Documents step and the claim workspace's Documents tab. */
export function useCorrectDocumentType(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (detectedType: DocumentType) =>
      apiFetch(`/documents/${id}`, { method: "PATCH", body: { detected_type: detectedType }, schema: storedDocumentSchema }),
    onSuccess: (doc) => {
      queryClient.setQueryData(queryKeys.documents.detail(id), doc);
      void queryClient.invalidateQueries({ queryKey: queryKeys.documents.all() });
    },
  });
}

export function useDeleteDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(`/documents/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.documents.all() });
    },
  });
}
