import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import type { Claim, ClaimState } from "@/api/types";
import { useClaims } from "@/api/endpoints/claims";
import { useMembers } from "@/api/endpoints/members";
import { ClaimCard, EmptyState, ErrorState, Skeleton } from "@/components/primitives";

/** Most urgent/active states first — a household should see what needs attention before what's settled. */
const GROUP_ORDER: ClaimState[] = [
  "denied",
  "escalated",
  "queried",
  "under_review",
  "documents_submitted",
  "intimated",
  "approved",
  "resolved",
  "unknown",
];

const GROUP_LABEL: Record<ClaimState, string> = {
  denied: "Denied",
  escalated: "Escalated",
  queried: "Query raised",
  under_review: "Under review",
  documents_submitted: "Documents submitted",
  intimated: "Intimated",
  approved: "Approved",
  resolved: "Resolved",
  unknown: "Status unavailable",
};

export function ClaimList() {
  const navigate = useNavigate();
  const claims = useClaims();
  const members = useMembers();

  const memberById = useMemo(() => new Map((members.data ?? []).map((m) => [m.id, m])), [members.data]);

  const groups = useMemo(() => {
    const byState = new Map<ClaimState, Claim[]>();
    for (const claim of claims.data ?? []) {
      const list = byState.get(claim.current_state) ?? [];
      list.push(claim);
      byState.set(claim.current_state, list);
    }
    return GROUP_ORDER.map((state) => ({ state, claims: byState.get(state) ?? [] })).filter((g) => g.claims.length > 0);
  }, [claims.data]);

  return (
    <div className="flex flex-col gap-6">
      <header className="flex items-center justify-between gap-3">
        <div>
          <h1 className="font-serif text-2xl font-semibold text-foreground">Claims</h1>
          <p className="text-sm text-muted-foreground">Every claim you've filed, grouped by where it stands.</p>
        </div>
        {claims.data && claims.data.length > 0 && (
          <button
            type="button"
            onClick={() => navigate("/claims/new")}
            className="rounded bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/85"
          >
            File a claim
          </button>
        )}
      </header>

      {claims.isPending && (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-28 w-full" />
        </div>
      )}

      {claims.isError && (
        <ErrorState message="We couldn't load your claims. Check your connection and try again." onRetry={() => claims.refetch()} />
      )}

      {claims.isSuccess && groups.length === 0 && (
        <EmptyState
          title="No claims yet"
          description="When you file a claim, it'll show up here with its status and any deadlines you need to track."
          action={{ label: "File a claim", onClick: () => navigate("/claims/new") }}
        />
      )}

      {claims.isSuccess &&
        groups.map((group) => (
          <section key={group.state} className="flex flex-col gap-3">
            <h2 className="font-serif text-lg font-semibold text-foreground">
              {GROUP_LABEL[group.state]} <span className="font-mono text-sm font-normal text-muted-foreground">({group.claims.length})</span>
            </h2>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {group.claims.map((claim) => (
                <ClaimCard key={claim.id} claim={claim} member={memberById.get(claim.member_id) ?? null} />
              ))}
            </div>
          </section>
        ))}
    </div>
  );
}
