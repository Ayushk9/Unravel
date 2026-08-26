import type { Alert } from "@/api/types";
import { stateClasses, stateIcon, type StateTone } from "./state";

const severityTone: Record<Alert["severity"], StateTone> = {
  info: "neutral",
  warning: "caution",
  critical: "negative",
  unknown: "neutral",
};

export interface AlertCardProps {
  alert: Alert;
  className?: string;
}

export function AlertCard({ alert, className }: AlertCardProps) {
  const tone = severityTone[alert.severity];
  const c = stateClasses[tone];
  const Icon = stateIcon[tone];

  return (
    <div className={`flex items-start gap-3 rounded border px-3 py-2.5 ${c.bg} ${c.border} ${className ?? ""}`}>
      <Icon className={`mt-0.5 size-4 shrink-0 ${c.text}`} aria-hidden="true" />
      <div className="flex flex-col gap-0.5">
        <span className={`text-sm font-semibold ${c.text}`}>{alert.title}</span>
        <p className="text-sm text-foreground">{alert.explanation}</p>
        {alert.suggested_action && <p className="text-xs text-muted-foreground">{alert.suggested_action}</p>}
        {alert.reference_source && <p className="text-xs text-muted-foreground italic">Source: {alert.reference_source}</p>}
      </div>
    </div>
  );
}
