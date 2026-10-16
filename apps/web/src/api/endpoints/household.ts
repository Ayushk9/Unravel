import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { HouseholdUpdateRequest } from "@/api/types";
import { apiFetch } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import { householdSchema } from "@/api/schemas";

/** D-40: the caller's own household. There is no household id anywhere in the request (D-10). */
export function useHousehold() {
  return useQuery({
    queryKey: queryKeys.household.detail(),
    queryFn: () => apiFetch(`/household`, { schema: householdSchema }),
  });
}

/** The room-rent alert reads the city tier, so alerts are refetched after a change. */
export function useUpdateHousehold() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: HouseholdUpdateRequest) => apiFetch(`/household`, { method: "PATCH", body, schema: householdSchema }),
    onSuccess: (household) => {
      queryClient.setQueryData(queryKeys.household.detail(), household);
      void queryClient.invalidateQueries({ queryKey: queryKeys.alerts.list() });
    },
  });
}
