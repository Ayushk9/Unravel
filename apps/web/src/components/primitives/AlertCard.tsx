import type { Alert, Provenance } from "@/api/types";
import { formatISTDate } from "@/lib/formatDate";
import { ProvenanceChip } from "./ProvenanceChip";
import { stateClasses, stateIcon, type StateTone } from "./state";

const severityTone: Record<Alert["severity"], StateTone> = {
  info: "neutral",
  warning: "caution",
  critical: "negative",
  unknown: "neutral",
};

export interface AlertCardProps {
  alert: Alert;
  onOpenProvenance?: (provenance: Provenance) => void;
  className?: string;
}

/**
 * One gap alert. D-38: an alert resting on a reference figure nobody has
 * checked (`verified: false`) is labelled an estimate, visibly, never
 * silently (product rule 6). Its provenance, when present, is the policy
 * clause it is based on; an alert about something not being found has none.
 */
export function AlertCard({ alert, onOpenProvenance, className }: AlertCardProps) {
  const tone = severityTone[alert.severity];
  const c = stateClasses[tone];
  const Icon = stateIcon[tone];

  return (
    <div className={`flex items-start gap-3 rounded border px-3 py-2.5 ${c.bg} ${c.border} ${className ?? ""}`}>
      <Icon className={`mt-0.5 size-4 shrink-0 ${c.text}`} aria-hidden="true" />
      <div className="flex min-w-0 flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className={`text-sm font-semibold ${c.text}`}>{alert.title}</span>
          {!alert.verified && (
            <span className="rounded border border-dashed border-caution-border bg-card px-1.5 py-0.5 text-[11px] font-medium text-caution">
              Estimate · not checked against a published source
            </span>
          )}
        </div>
        <p className="text-sm text-foreground">{alert.explanation}</p>
        {alert.suggested_action && <p className="text-xs text-muted-foreground">{alert.suggested_action}</p>}
        {alert.triggers_on && <p className="text-xs text-muted-foreground">Date: {formatISTDate(alert.triggers_on)}</p>}
        {alert.reference_source && <p className="text-xs text-muted-foreground italic">Source: {alert.reference_source}</p>}
        {alert.provenance && <ProvenanceChip provenance={alert.provenance} userConfirmed={false} onOpen={onOpenProvenance} className="w-fit" />}
      </div>
    </div>
  );
}
