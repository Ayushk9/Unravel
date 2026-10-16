import { useState } from "react";
import { Link } from "react-router-dom";
import type { Provenance } from "@/api/types";
import { useAlerts } from "@/api/endpoints/alerts";
import { useHousehold } from "@/api/endpoints/household";
import { usePolicies } from "@/api/endpoints/policies";
import { AlertCard, EmptyState, ErrorState, Skeleton } from "@/components/primitives";
import { ProvenanceModal } from "@/components/ProvenanceModal";
import { productLabel } from "@/lib/policyLabels";

/**
 * Feature 8: gaps in the household's cover, worked out by the server on
 * every request (D-38). Grouped by policy. An alert that rests on an
 * unchecked reference figure is labelled as an estimate on its card.
 */
export function Alerts() {
  const alerts = useAlerts();
  const policies = usePolicies();
  const household = useHousehold();
  const [viewerProvenance, setViewerProvenance] = useState<Provenance | null>(null);

  const policyName = (id: string) => {
    const policy = (policies.data ?? []).find((p) => p.id === id);
    return policy ? productLabel(policy) : "Policy";
  };
  const policyIds = [...new Set((alerts.data ?? []).map((a) => a.policy_id))];

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="font-serif text-2xl font-semibold text-foreground">Alerts</h1>
        <p className="text-sm text-muted-foreground">Gaps and upcoming dates in your cover, worked out from your policies today.</p>
      </header>

      {/* Abstained input: the room-rent alert can't run until the household says what kind of city it lives in. */}
      {household.isSuccess && household.data.city_tier === null && (
        <p className="rounded border border-neutral-border bg-neutral-bg px-4 py-3 text-sm text-neutral">
          We can't compare your room rent cap with typical local rates until you tell us what kind of city you live in.{" "}
          <Link to="/settings" className="font-medium underline underline-offset-2">
            Choose it in Settings
          </Link>
          .
        </p>
      )}

      {alerts.isPending && (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      )}
      {alerts.isError && <ErrorState message="We couldn't load your alerts. Check your connection and try again." onRetry={() => alerts.refetch()} />}
      {alerts.isSuccess && alerts.data.length === 0 && (
        <EmptyState
          title="Nothing needs your attention"
          description="When a waiting period is about to end, a renewal is due, or your cover looks thin, it will show up here."
        />
      )}
      {alerts.isSuccess &&
        policyIds.map((policyId) => (
          <section key={policyId} className="flex flex-col gap-2">
            <h2 className="font-serif text-lg font-semibold text-foreground">{policyName(policyId)}</h2>
            {alerts.data
              .filter((a) => a.policy_id === policyId)
              .map((alert) => (
                <AlertCard key={alert.id} alert={alert} onOpenProvenance={setViewerProvenance} />
              ))}
          </section>
        ))}

      <ProvenanceModal provenance={viewerProvenance} onClose={() => setViewerProvenance(null)} title="Where this comes from" />
    </div>
  );
}
