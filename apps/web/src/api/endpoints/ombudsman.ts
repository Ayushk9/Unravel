import { useInfiniteQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import { collectionSchema, ombudsmanAwardSchema } from "@/api/schemas";

const ombudsmanAwardsPageSchema = collectionSchema(ombudsmanAwardSchema);

export function useOmbudsmanAwards() {
  return useInfiniteQuery({
    queryKey: queryKeys.ombudsmanAwards.list(null),
    queryFn: ({ pageParam }) => {
      const search = pageParam ? `?cursor=${encodeURIComponent(pageParam)}` : "";
      return apiFetch(`/ombudsman-awards${search}`, { schema: ombudsmanAwardsPageSchema });
    },
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
  });
}
