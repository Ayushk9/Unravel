import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { z } from "zod";
import { apiFetch } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import { jobSchema } from "@/api/schemas";

/**
 * D-08's polling policy, in one place so every job-backed feature (upload
 * review, Q&A, grievance drafting) gets it identically: every 1s for the
 * first 10s, then every 3s, hard timeout at 180s. The backend keeps terminal
 * job records for 24h, so a page refresh can still recover a result that
 * finished after the tab was closed — this hook just re-polls from scratch
 * on mount, which naturally picks that up.
 */
export function useJobPolling<TResult>(jobId: string | null, resultSchema: z.ZodType<TResult>) {
  const [startedAt, setStartedAt] = useState<number | null>(null);

  useEffect(() => {
    setStartedAt(jobId ? Date.now() : null);
  }, [jobId]);

  const schema = jobSchema(resultSchema);

  const query = useQuery({
    queryKey: queryKeys.jobs.detail(jobId ?? "none"),
    queryFn: () => apiFetch(`/jobs/${jobId}`, { schema }),
    enabled: jobId !== null,
    refetchInterval: (currentQuery) => {
      const data = currentQuery.state.data;
      if (data && (data.status === "succeeded" || data.status === "failed")) return false;
      const elapsed = startedAt ? Date.now() - startedAt : 0;
      if (elapsed > 180_000) return false;
      return elapsed < 10_000 ? 1000 : 3000;
    },
  });

  const elapsed = startedAt ? Date.now() - startedAt : 0;
  const timedOut = elapsed > 180_000 && query.data?.status !== "succeeded" && query.data?.status !== "failed";

  return { ...query, timedOut };
}
