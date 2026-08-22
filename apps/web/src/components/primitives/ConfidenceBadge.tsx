import { BadgeCheck } from "lucide-react";
import type { Confidence } from "@/api/types";
import { stateClasses, stateIcon, type StateTone } from "./state";

/**
 * Shows extraction confidence. A user_confirmed field overrides the tier
 * entirely and shows "Confirmed" — confirmation supersedes the model's
 * original confidence (see ProvenanceChip for the "no provenance at all"
 * case, which is a different, stricter signal).
 */
const tierTone: Record<Confidence, StateTone> = {
  high: "positive",
  medium: "caution",
  low: "negative",
};

const tierLabel: Record<Confidence, string> = {
  high: "High confidence",
  medium: "Medium confidence — worth checking",
  low: "Low confidence — review this value",
};

export interface ConfidenceBadgeProps {
  confidence: Confidence;
  userConfirmed?: boolean;
  className?: string;
}

export function ConfidenceBadge({ confidence, userConfirmed = false, className }: ConfidenceBadgeProps) {
  if (userConfirmed) {
    const c = stateClasses.positive;
    return (
      <span
        className={`inline-flex items-center gap-1.5 rounded border px-2 py-0.5 text-xs font-medium ${c.text} ${c.bg} ${c.border} ${className ?? ""}`}
      >
        <BadgeCheck className="size-3.5" aria-hidden="true" />
        Confirmed
      </span>
    );
  }

  const tone = tierTone[confidence];
  const c = stateClasses[tone];
  const Icon = stateIcon[tone];

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded border px-2 py-0.5 text-xs font-medium ${c.text} ${c.bg} ${c.border} ${className ?? ""}`}
    >
      <Icon className="size-3.5" aria-hidden="true" />
      {tierLabel[confidence]}
    </span>
  );
}
