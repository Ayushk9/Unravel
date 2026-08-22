import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";

interface HealthResponse {
  status: "ok";
}

export function useHealthCheck() {
  return useQuery({
    queryKey: queryKeys.health(),
    queryFn: () => apiFetch<HealthResponse>("/health"),
  });
}
