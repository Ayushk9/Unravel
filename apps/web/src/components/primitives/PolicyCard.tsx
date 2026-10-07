import { Link } from "react-router-dom";
import { Building2 } from "lucide-react";
import type { Policy } from "@/api/types";
import { formatISTDate } from "@/lib/formatDate";
import { insurerLabel, productLabel } from "@/lib/policyLabels";
import { Money } from "./Money";
import { ConfidenceBadge } from "./ConfidenceBadge";

const policyTypeLabel: Record<Policy["policy_type"], string> = {
  individual: "Individual",
  family_floater: "Family floater",
  group_employer: "Employer group",
  top_up: "Top-up",
  other: "Other",
};

export interface PolicyCardProps {
  policy: Policy;
  selectable?: { selected: boolean; onToggle: () => void };
  className?: string;
}

/** Summary card — dashboard and policy list both use this. */
export function PolicyCard({ policy, selectable, className }: PolicyCardProps) {
  const content = (
    <>
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <Building2 className="size-4 shrink-0 text-ink-muted" aria-hidden="true" />
          <span className="font-serif text-base font-semibold text-foreground">{insurerLabel(policy)}</span>
        </div>
        <span className="rounded border border-rule bg-card px-1.5 py-0.5 text-xs text-muted-foreground">
          {policyTypeLabel[policy.policy_type]}
        </span>
      </div>
      <p className="text-sm text-muted-foreground">{productLabel(policy)}</p>
      <div className="mt-1 flex items-baseline justify-between gap-2">
        <span className="text-xs text-muted-foreground">Sum insured</span>
        <span className="flex items-center gap-1.5">
          <Money value={policy.coverage_profile?.sum_insured.value ?? null} className="text-base font-semibold" />
          {policy.coverage_profile && !policy.coverage_profile.sum_insured.user_confirmed && (
            <ConfidenceBadge
              confidence={policy.coverage_profile.sum_insured.confidence}
              userConfirmed={policy.coverage_profile.sum_insured.user_confirmed}
            />
          )}
        </span>
      </div>
      <p className="font-tabular text-xs font-mono text-muted-foreground">{policy.end_date ? `Ends ${formatISTDate(policy.end_date)}` : "End date not stated"}</p>
    </>
  );

  const baseClasses = `flex flex-col gap-1 rounded border border-rule bg-card px-4 py-3 ${className ?? ""}`;

  if (selectable) {
    return (
      <label className={`${baseClasses} cursor-pointer ${selectable.selected ? "border-stamp ring-1 ring-stamp" : ""}`}>
        <div className="mb-1 flex items-center gap-2">
          <input type="checkbox" checked={selectable.selected} onChange={selectable.onToggle} className="size-4 accent-stamp" />
          <span className="text-xs text-muted-foreground">Compare</span>
        </div>
        {content}
      </label>
    );
  }

  return (
    <Link to={`/policies/${policy.id}`} className={`${baseClasses} transition-colors hover:border-ink`}>
      {content}
    </Link>
  );
}
