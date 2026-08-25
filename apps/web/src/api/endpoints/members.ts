import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { apiFetch } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import { memberSchema } from "@/api/schemas";

const membersListSchema = z.array(memberSchema);

/** Unpaginated (API_DECISIONS.md §5) — a household has a handful of members. */
export function useMembers() {
  return useQuery({
    queryKey: queryKeys.members.list(),
    queryFn: () => apiFetch(`/members`, { schema: membersListSchema }),
  });
}
