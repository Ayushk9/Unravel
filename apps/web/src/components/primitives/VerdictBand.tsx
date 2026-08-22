import type { EligibilityAssessment } from "@/api/types";
import { stateClasses, stateIcon, type StateTone } from "./state";

/**
 * The eligibility verdict. No percentage, no gauge, no arc — a labelled band
 * plus the plain-language sentence explaining it. The checks that produced
 * the verdict render separately, beneath this (not this component's job).
 */
type Band = EligibilityAssessment["band"];

const bandTone: Record<Band, StateTone> = {
  likely_eligible: "positive",
  at_risk: "caution",
  likely_ineligible: "negative",
  insufficient_information: "neutral",
};

const bandLabel: Record<Band, string> = {
  likely_eligible: "Likely eligible",
  at_risk: "At risk",
  likely_ineligible: "Likely ineligible",
  insufficient_information: "Insufficient information",
};

export interface VerdictBandProps {
  band: Band;
  explanation: string;
  className?: string;
}

export function VerdictBand({ band, explanation, className }: VerdictBandProps) {
  const tone = bandTone[band];
  const c = stateClasses[tone];
  const Icon = stateIcon[tone];

  return (
    <div
      role="status"
      className={`flex items-start gap-3 rounded border-2 px-4 py-3 ${c.bg} ${c.border} ${className ?? ""}`}
    >
      <Icon className={`size-6 shrink-0 ${c.text}`} aria-hidden="true" />
      <div className="flex flex-col gap-1">
        <span className={`font-serif text-lg font-semibold ${c.text}`}>{bandLabel[band]}</span>
        <p className="text-sm text-foreground">{explanation}</p>
      </div>
    </div>
  );
}
