import { Scale } from "lucide-react";
import type { OmbudsmanAward } from "@/api/types";
import { formatISTDate } from "@/lib/formatDate";
import { stateClasses, type StateTone } from "./state";

const outcomeTone: Record<OmbudsmanAward["outcome"], StateTone> = {
  overturned: "positive",
  upheld: "negative",
  partially_allowed: "caution",
  unknown: "neutral",
};

const outcomeLabel: Record<OmbudsmanAward["outcome"], string> = {
  overturned: "Denial overturned",
  upheld: "Denial upheld",
  partially_allowed: "Partially allowed",
  unknown: "Outcome not reported",
};

export interface PrecedentCardProps {
  award: OmbudsmanAward;
  className?: string;
}

/** One Ombudsman award in the eligibility precedent panel — a fact pattern and outcome, never framed as a prediction about the current claim. */
export function PrecedentCard({ award, className }: PrecedentCardProps) {
  const c = stateClasses[outcomeTone[award.outcome]];

  return (
    <div className={`flex flex-col gap-1.5 rounded border border-rule bg-card px-4 py-3 ${className ?? ""}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-foreground">
          <Scale className="size-4 shrink-0 text-ink-muted" aria-hidden="true" />
          {award.case_reference}
        </span>
        <span className={`inline-flex items-center rounded border px-2 py-0.5 text-xs font-medium ${c.text} ${c.bg} ${c.border}`}>
          {outcomeLabel[award.outcome]}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">
        {award.insurer_name} · Decided {formatISTDate(award.decided_on)} · Ground: {award.denial_ground}
      </p>
      <p className="text-sm text-foreground">{award.summary}</p>
    </div>
  );
}
