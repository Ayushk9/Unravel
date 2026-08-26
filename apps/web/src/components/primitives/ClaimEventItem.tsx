import { HelpCircle, Mail, Settings2, User } from "lucide-react";
import type { ClaimEvent } from "@/api/types";
import { formatISTDate } from "@/lib/formatDate";
import { claimStateLabel } from "./ClaimStateBadge";

const sourceIcon: Record<ClaimEvent["source"], typeof User> = {
  user: User,
  insurer_letter: Mail,
  system: Settings2,
  unknown: HelpCircle,
};

const sourceLabel: Record<ClaimEvent["source"], string> = {
  user: "You",
  insurer_letter: "Insurer letter",
  system: "System",
  unknown: "Unknown source",
};

export interface ClaimEventItemProps {
  event: ClaimEvent;
  isLast?: boolean;
  className?: string;
}

/** One entry in the vertical claim event timeline — rendered directly from the append-only event log, newest first. */
export function ClaimEventItem({ event, isLast = false, className }: ClaimEventItemProps) {
  const Icon = sourceIcon[event.source];

  return (
    <li className={`flex gap-3 ${className ?? ""}`}>
      <div className="flex flex-col items-center">
        <span className="flex size-7 shrink-0 items-center justify-center rounded-full border-2 border-ink bg-card">
          <Icon className="size-3.5 text-ink-muted" aria-hidden="true" />
        </span>
        {!isLast && <span className="w-px flex-1 bg-rule" aria-hidden="true" />}
      </div>
      <div className="flex flex-1 flex-col gap-0.5 pb-6">
        <div className="flex flex-wrap items-baseline gap-2">
          <span className="font-serif text-sm font-semibold text-foreground">
            {event.from_state ? `${claimStateLabel[event.from_state]} → ` : ""}
            {claimStateLabel[event.to_state]}
          </span>
          <span className="font-tabular font-mono text-xs text-muted-foreground">{formatISTDate(event.occurred_at)}</span>
        </div>
        <span className="text-xs tracking-wide text-muted-foreground uppercase">{sourceLabel[event.source]}</span>
        {event.note && <p className="text-sm text-foreground">{event.note}</p>}
      </div>
    </li>
  );
}
