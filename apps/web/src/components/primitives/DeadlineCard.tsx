import { AlarmClock, AlertCircle, CalendarX, Clock, HelpCircle, ShieldQuestion } from "lucide-react";
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
  unknown: HelpCircle,
};

const urgencyClasses: Record<Urgency, string> = {
  normal: "border-rule bg-card text-ink-muted",
  soon: "border-caution-border bg-caution-bg text-caution",
  critical: "border-negative-border bg-negative-bg text-flag",
  expired: "border-rule bg-card text-ink-muted opacity-70",
  unknown: "border-neutral-border bg-neutral-bg text-neutral",
};

const urgencyLabel: Record<Urgency, string> = {
  normal: "Upcoming",
  soon: "Due soon",
  critical: "Critical",
  expired: "Expired",
  unknown: "Urgency not reported",
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
        {/* D-33: a rule nobody has checked against its source is marked, with an icon and words, not colour alone. */}
        {!deadline.verified && (
          <span className="ml-auto inline-flex items-center gap-1 rounded border border-caution-border bg-caution-bg px-1.5 py-0.5 text-xs font-semibold text-caution">
            <ShieldQuestion className="size-3.5 shrink-0" aria-hidden="true" />
            Unverified rule
          </span>
        )}
      </div>
      <p className="mt-1.5 font-serif text-base font-semibold text-foreground">{deadline.label}</p>
      <p className="font-tabular mt-0.5 font-mono text-sm">
        {deadline.urgency === "expired"
          ? `Expired on ${formatISTDate(deadline.due_at)}`
          : `${formatISTDate(deadline.due_at)} · ${deadline.days_remaining} day${deadline.days_remaining === 1 ? "" : "s"} remaining`}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">{deadline.basis}</p>
      {deadline.source && (
        <p className="mt-1 text-xs text-muted-foreground">
          Source: {deadline.source.document}
          {deadline.source.section ? `, ${deadline.source.section}` : ""}
        </p>
      )}
      {!deadline.verified && (
        <p className="mt-1 text-xs font-medium text-caution">
          This date is an estimate. The rule behind it has not been checked against the official source yet, so confirm it before you rely on it.
        </p>
      )}
    </div>
  );
}
