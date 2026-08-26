import type { Provenance, SubLimit } from "@/api/types";
import { Money } from "./Money";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { ProvenanceChip } from "./ProvenanceChip";

const basisLabel: Record<SubLimit["cap_basis"], string> = {
  per_day: "per day",
  per_claim: "per claim",
  per_policy_year: "per policy year",
  percent_of_sum_insured: "% of sum insured",
  other: "other basis",
};

export interface SubLimitsTableProps {
  subLimits: SubLimit[];
  onOpenProvenance?: (provenance: Provenance) => void;
  className?: string;
}

export function SubLimitsTable({ subLimits, onOpenProvenance, className }: SubLimitsTableProps) {
  if (subLimits.length === 0) {
    return <p className="text-sm text-muted-foreground">No sub-limits extracted from this policy.</p>;
  }

  return (
    <div className={`overflow-x-auto rounded border border-rule ${className ?? ""}`}>
      <table className="w-full min-w-[480px] border-collapse text-sm">
        <thead>
          <tr className="border-b border-rule bg-card text-left text-xs text-muted-foreground uppercase">
            <th scope="col" className="px-3 py-2 font-medium">
              Category
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Cap
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Confidence
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Source
            </th>
          </tr>
        </thead>
        <tbody>
          {subLimits.map((subLimit) => (
            <tr key={subLimit.category} className="border-b border-rule last:border-0">
              <td className="px-3 py-2 align-top text-foreground">{subLimit.label}</td>
              <td className="font-tabular px-3 py-2 align-top font-mono">
                {subLimit.percent_value !== null ? (
                  `${subLimit.percent_value}%`
                ) : (
                  <Money value={subLimit.cap_amount.value} />
                )}{" "}
                <span className="text-xs text-muted-foreground">{basisLabel[subLimit.cap_basis]}</span>
              </td>
              <td className="px-3 py-2 align-top">
                <ConfidenceBadge confidence={subLimit.cap_amount.confidence} userConfirmed={subLimit.cap_amount.user_confirmed} />
              </td>
              <td className="px-3 py-2 align-top">
                <ProvenanceChip
                  provenance={subLimit.cap_amount.provenance}
                  userConfirmed={subLimit.cap_amount.user_confirmed}
                  onOpen={onOpenProvenance}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
