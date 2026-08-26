import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { apiFetch } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import { insurerBenchmarkSchema } from "@/api/schemas";

const benchmarksListSchema = z.array(insurerBenchmarkSchema);

export function useInsurerBenchmarks() {
  return useQuery({
    queryKey: queryKeys.insurerBenchmarks.list(),
    queryFn: () => apiFetch(`/insurers/benchmarks`, { schema: benchmarksListSchema }),
  });
}
