import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { apiFetch } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import { alertSchema } from "@/api/schemas";

const alertsListSchema = z.array(alertSchema);

export function useAlerts() {
  return useQuery({
    queryKey: queryKeys.alerts.list(),
    queryFn: () => apiFetch(`/alerts`, { schema: alertsListSchema }),
  });
}
