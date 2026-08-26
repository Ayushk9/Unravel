import { Link, useNavigate } from "react-router-dom";
import { usePolicies } from "@/api/endpoints/policies";
import { useClaims } from "@/api/endpoints/claims";
import { useAlerts } from "@/api/endpoints/alerts";
import { AlertCard, EmptyState, ErrorState, PolicyCard, Skeleton } from "@/components/primitives";

const claimStateLabel: Record<string, string> = {
  intimated: "Intimated",
  documents_submitted: "Documents submitted",
  under_review: "Under review",
  queried: "Query raised",
  approved: "Approved",
  denied: "Denied",
  escalated: "Escalated",
  resolved: "Resolved",
  unknown: "Status unavailable",
};

export function Dashboard() {
  const navigate = useNavigate();
  const policies = usePolicies();
  const claims = useClaims();
  const alerts = useAlerts();

  const activeClaims = (claims.data ?? []).filter((c) => c.current_state !== "resolved");
  const topAlerts = (alerts.data ?? []).slice(0, 3);

  return (
    <div className="flex flex-col gap-8">
      <header>
        <h1 className="font-serif text-2xl font-semibold text-foreground">Household overview</h1>
        <p className="text-sm text-muted-foreground">Every policy, active claim, and thing worth your attention, in one place.</p>
      </header>

      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h2 className="font-serif text-lg font-semibold text-foreground">Policies</h2>
          {policies.data && policies.data.length > 0 && (
            <Link to="/policies" className="text-sm text-stamp underline underline-offset-2">
              View all
            </Link>
          )}
        </div>

        {policies.isPending && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Skeleton className="h-32 w-full" />
            <Skeleton className="h-32 w-full" />
          </div>
        )}

        {policies.isError && (
          <ErrorState
            message="We couldn't load your policies. Check your connection and try again."
            onRetry={() => policies.refetch()}
          />
        )}

        {policies.isSuccess && policies.data.length === 0 && (
          <EmptyState
            title="No policies yet"
            description="Upload a policy document and we'll extract its coverage terms — sum insured, sub-limits, waiting periods — for you to review."
            action={{ label: "Upload a policy", onClick: () => navigate("/policies/upload") }}
          />
        )}

        {policies.isSuccess && policies.data.length > 0 && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {policies.data.map((policy) => (
              <PolicyCard key={policy.id} policy={policy} />
            ))}
          </div>
        )}
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="font-serif text-lg font-semibold text-foreground">Active claims</h2>

        {claims.isPending && <Skeleton className="h-16 w-full" />}
        {claims.isError && (
          <ErrorState message="We couldn't load your claims. Check your connection and try again." onRetry={() => claims.refetch()} />
        )}
        {claims.isSuccess && activeClaims.length === 0 && (
          <EmptyState title="No active claims" description="Claims you file will show up here with their current status and deadlines." />
        )}
        {claims.isSuccess && activeClaims.length > 0 && (
          <div className="flex gap-3 overflow-x-auto pb-1">
            {activeClaims.map((claim) => (
              <div key={claim.id} className="flex min-w-56 shrink-0 flex-col gap-1 rounded border border-rule bg-card px-3 py-2.5">
                <span className="text-sm font-medium text-foreground">{claim.hospital_name}</span>
                <span className="text-xs text-muted-foreground">{claimStateLabel[claim.current_state] ?? claim.current_state}</span>
                {claim.deadlines[0] && (
                  <span className="font-tabular font-mono text-xs text-caution">
                    {claim.deadlines[0].label}: {claim.deadlines[0].days_remaining >= 0 ? `${claim.deadlines[0].days_remaining}d left` : "expired"}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h2 className="font-serif text-lg font-semibold text-foreground">Top alerts</h2>
          {alerts.data && alerts.data.length > 3 && (
            <Link to="/alerts" className="text-sm text-stamp underline underline-offset-2">
              View all
            </Link>
          )}
        </div>

        {alerts.isPending && <Skeleton className="h-16 w-full" />}
        {alerts.isError && (
          <ErrorState message="We couldn't load your alerts. Check your connection and try again." onRetry={() => alerts.refetch()} />
        )}
        {alerts.isSuccess && topAlerts.length === 0 && <EmptyState title="Nothing needs your attention" description="We'll surface coverage gaps and upcoming deadlines here as they come up." />}
        {alerts.isSuccess && topAlerts.length > 0 && (
          <div className="flex flex-col gap-2">
            {topAlerts.map((alert) => (
              <AlertCard key={alert.id} alert={alert} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
