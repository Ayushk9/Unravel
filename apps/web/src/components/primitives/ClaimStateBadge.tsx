import type { ClaimState } from "@/api/types";
import { stateClasses, stateIcon, type StateTone } from "./state";

const stateTone: Record<ClaimState, StateTone> = {
  intimated: "neutral",
  documents_submitted: "neutral",
  under_review: "caution",
  queried: "caution",
  approved: "positive",
  denied: "negative",
  escalated: "caution",
  resolved: "positive",
  unknown: "neutral",
};

export const claimStateLabel: Record<ClaimState, string> = {
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

export interface ClaimStateBadgeProps {
  state: ClaimState;
  className?: string;
}

export function ClaimStateBadge({ state, className }: ClaimStateBadgeProps) {
  const tone = stateTone[state];
  const c = stateClasses[tone];
  const Icon = stateIcon[tone];

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded border px-2 py-0.5 text-xs font-medium ${c.text} ${c.bg} ${c.border} ${className ?? ""}`}
    >
      <Icon className="size-3.5" aria-hidden="true" />
      {claimStateLabel[state]}
    </span>
  );
}
