import { AlarmClock, AlertCircle, CalendarX, Clock } from "lucide-react";
import type { Deadline } from "@/api/types";
import { formatISTDate } from "@/lib/formatDate";

/**
 * `due_at` and `days_remaining` are always server-computed (D-17) — this
 * component only displays them, never derives them from the client clock.
 * `expired` deadlines stay visible with their own treatment rather than
 * disappearing, so a past deadline is still auditable.
 */
type Urgency = Deadline["urgency"];

const urgencyIcon: Record<Urgency, typeof Clock> = {
  normal: Clock,
  soon: AlarmClock,
  critical: AlertCircle,
  expired: CalendarX,
};

const urgencyClasses: Record<Urgency, string> = {
  normal: "border-rule bg-card text-ink-muted",
  soon: "border-caution-border bg-caution-bg text-caution",
  critical: "border-negative-border bg-negative-bg text-flag",
  expired: "border-rule bg-card text-ink-muted opacity-70",
};

const urgencyLabel: Record<Urgency, string> = {
  normal: "Upcoming",
  soon: "Due soon",
  critical: "Critical",
  expired: "Expired",
};

export interface DeadlineCardProps {
  deadline: Deadline;
  className?: string;
}

export function DeadlineCard({ deadline, className }: DeadlineCardProps) {
  const Icon = urgencyIcon[deadline.urgency];

  return (
    <div className={`rounded border px-4 py-3 ${urgencyClasses[deadline.urgency]} ${className ?? ""}`}>
      <div className="flex items-center gap-2">
        <Icon className="size-4 shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold tracking-wide uppercase">{urgencyLabel[deadline.urgency]}</span>
      </div>
      <p className="mt-1.5 font-serif text-base font-semibold text-foreground">{deadline.label}</p>
      <p className="font-tabular mt-0.5 font-mono text-sm">
        {deadline.urgency === "expired"
          ? `Expired on ${formatISTDate(deadline.due_at)}`
          : `${formatISTDate(deadline.due_at)} · ${deadline.days_remaining} day${deadline.days_remaining === 1 ? "" : "s"} remaining`}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">{deadline.basis}</p>
    </div>
  );
}
