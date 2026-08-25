import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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

export function useDeleteDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(`/documents/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.documents.all() });
    },
  });
}
