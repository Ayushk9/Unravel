import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Columns3 } from "lucide-react";
import type { Policy, SubLimit, WaitingPeriod } from "@/api/types";
import { usePolicies } from "@/api/endpoints/policies";
import { EmptyState, ErrorState, Money, PolicyCard, Skeleton } from "@/components/primitives";

const subLimitCategoryLabel: Record<SubLimit["category"], string> = {
  room_rent: "Room rent",
  icu: "ICU",
  procedure: "Procedure",
  ambulance: "Ambulance",
  opd: "OPD",
  other: "Other",
};
const waitingKindLabel: Record<WaitingPeriod["kind"], string> = {
  initial: "Initial waiting period",
  disease_specific: "Disease-specific waiting period",
  pre_existing: "Pre-existing disease waiting period",
  maternity: "Maternity waiting period",
  other: "Waiting period",
};

function isExcluded(policy: Policy, keyword: string): boolean {
  return (policy.coverage_profile?.exclusions ?? []).some((e) => e.value?.toLowerCase().includes(keyword.toLowerCase()));
}

function ComparisonTable({ policies }: { policies: Policy[] }) {
  const subLimitCategories = useMemo(() => {
    const set = new Set<SubLimit["category"]>();
    for (const p of policies) for (const s of p.coverage_profile?.sub_limits ?? []) set.add(s.category);
    return [...set];
  }, [policies]);

  const waitingKinds = useMemo(() => {
    const set = new Set<WaitingPeriod["kind"]>();
    for (const p of policies) for (const w of p.coverage_profile?.waiting_periods ?? []) set.add(w.kind);
    return [...set];
  }, [policies]);

  return (
    <div className="overflow-x-auto rounded border border-rule">
      <table className="w-full min-w-[560px] border-collapse text-sm">
        <thead>
          <tr className="border-b border-rule bg-card text-left">
            <th scope="col" className="px-3 py-2 text-xs font-medium text-muted-foreground uppercase">
              Term
            </th>
            {policies.map((p) => (
              <th key={p.id} scope="col" className="px-3 py-2 font-serif font-semibold text-foreground">
                {p.insurer.name}
                <span className="block text-xs font-normal text-muted-foreground">{p.product_name}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr className="border-b border-rule">
            <td className="px-3 py-2 text-muted-foreground">Sum insured</td>
            {policies.map((p) => (
              <td key={p.id} className="px-3 py-2">
                <Money value={p.coverage_profile?.sum_insured.value ?? null} />
              </td>
            ))}
          </tr>
          {subLimitCategories.map((category) => (
            <tr key={category} className="border-b border-rule">
              <td className="px-3 py-2 text-muted-foreground">{subLimitCategoryLabel[category]} cap</td>
              {policies.map((p) => {
                const subLimit = p.coverage_profile?.sub_limits.find((s) => s.category === category);
                return (
                  <td key={p.id} className="px-3 py-2">
                    {subLimit ? <Money value={subLimit.cap_amount.value} /> : <span className="text-muted-foreground">Not mentioned</span>}
                  </td>
                );
              })}
            </tr>
          ))}
          {waitingKinds.map((kind) => (
            <tr key={kind} className="border-b border-rule last:border-0">
              <td className="px-3 py-2 text-muted-foreground">{waitingKindLabel[kind]}</td>
              {policies.map((p) => {
                const waitingPeriod = p.coverage_profile?.waiting_periods.find((w) => w.kind === kind);
                if (waitingPeriod) {
                  return (
                    <td key={p.id} className="font-tabular px-3 py-2 font-mono">
                      {waitingPeriod.months.value} months
                    </td>
                  );
                }
                const excluded = kind === "maternity" && isExcluded(p, "maternity");
                return (
                  <td key={p.id} className={`px-3 py-2 ${excluded ? "text-flag" : "text-muted-foreground"}`}>
                    {excluded ? "Excluded" : "Not mentioned"}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function PolicyList() {
  const navigate = useNavigate();
  const policies = usePolicies();
  const [compareMode, setCompareMode] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);

  function toggleSelected(id: string) {
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : prev.length < 2 ? [...prev, id] : [prev[1]!, id]));
  }

  const selectedPolicies = (policies.data ?? []).filter((p) => selected.includes(p.id));

  return (
    <div className="flex flex-col gap-6">
      <header className="flex items-center justify-between gap-3">
        <div>
          <h1 className="font-serif text-2xl font-semibold text-foreground">Policies</h1>
          <p className="text-sm text-muted-foreground">All your policies, in one place.</p>
        </div>
        {policies.data && policies.data.length > 0 && (
          <button
            type="button"
            onClick={() => setCompareMode((v) => !v)}
            className={`inline-flex items-center gap-1.5 rounded border px-3 py-1.5 text-sm font-medium ${
              compareMode ? "border-stamp bg-positive-bg text-stamp" : "border-rule text-foreground hover:bg-secondary"
            }`}
          >
            <Columns3 className="size-4" aria-hidden="true" />
            Compare
          </button>
        )}
      </header>

      {policies.isPending && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-32 w-full" />
        </div>
      )}

      {policies.isError && (
        <ErrorState message="We couldn't load your policies. Check your connection and try again." onRetry={() => policies.refetch()} />
      )}

      {policies.isSuccess && policies.data.length === 0 && (
        <EmptyState
          title="No policies yet"
          description="Upload a policy document and we'll extract its coverage terms for you to review."
          action={{ label: "Upload a policy", onClick: () => navigate("/policies/upload") }}
        />
      )}

      {policies.isSuccess && policies.data.length > 0 && (
        <>
          {compareMode && (
            <p className="text-sm text-muted-foreground">Select two policies to align their sub-limits and waiting periods side by side.</p>
          )}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {policies.data.map((policy) =>
              compareMode ? (
                <PolicyCard
                  key={policy.id}
                  policy={policy}
                  selectable={{ selected: selected.includes(policy.id), onToggle: () => toggleSelected(policy.id) }}
                />
              ) : (
                <PolicyCard key={policy.id} policy={policy} />
              ),
            )}
          </div>

          {compareMode && selectedPolicies.length === 2 && (
            <section className="flex flex-col gap-2">
              <h2 className="font-serif text-lg font-semibold text-foreground">Comparison</h2>
              <ComparisonTable policies={selectedPolicies} />
            </section>
          )}
        </>
      )}
    </div>
  );
}
