import type { WaitingPeriod } from "@/api/types";
import { formatISTDate } from "@/lib/formatDate";
import { ConfidenceBadge } from "./ConfidenceBadge";

const kindLabel: Record<WaitingPeriod["kind"], string> = {
  initial: "Initial waiting period",
  disease_specific: "Disease-specific waiting period",
  pre_existing: "Pre-existing disease waiting period",
  maternity: "Maternity waiting period",
  other: "Waiting period",
};

function monthsElapsedFraction(startsOn: string | null, expiresOn: string | null): number | null {
  if (!startsOn || !expiresOn) return null;
  const start = Date.parse(startsOn);
  const end = Date.parse(expiresOn);
  const now = Date.now();
  if (end <= start) return null;
  return Math.min(1, Math.max(0, (now - start) / (end - start)));
}

export interface WaitingPeriodTimelineProps {
  waitingPeriod: WaitingPeriod;
  className?: string;
}

/** A horizontal track showing months served vs remaining, per brief §6.1. */
export function WaitingPeriodTimeline({ waitingPeriod, className }: WaitingPeriodTimelineProps) {
  const fraction = monthsElapsedFraction(waitingPeriod.starts_on, waitingPeriod.expires_on);
  const expired = fraction !== null && fraction >= 1;

  return (
    <div className={`flex flex-col gap-1.5 rounded border border-rule bg-card px-3 py-2.5 ${className ?? ""}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-medium text-foreground">
          {kindLabel[waitingPeriod.kind]}
          {waitingPeriod.applies_to && <span className="text-muted-foreground"> · {waitingPeriod.applies_to}</span>}
        </span>
        <ConfidenceBadge confidence={waitingPeriod.months.confidence} userConfirmed={waitingPeriod.months.user_confirmed} />
      </div>

      <p className="font-tabular text-sm font-mono text-muted-foreground">
        {waitingPeriod.months.value !== null ? `${waitingPeriod.months.value} months` : "Duration not extracted"}
      </p>

      {fraction !== null ? (
        <>
          <div
            role="progressbar"
            aria-valuenow={Math.round(fraction * 100)}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={`${kindLabel[waitingPeriod.kind]} progress`}
            className="h-2 w-full overflow-hidden rounded-full bg-rule"
          >
            <div
              className={`h-full rounded-full ${expired ? "bg-stamp" : "bg-caution"}`}
              style={{ width: `${fraction * 100}%` }}
            />
          </div>
          <p className="font-tabular text-xs font-mono text-muted-foreground">
            {expired
              ? `Expired on ${formatISTDate(waitingPeriod.expires_on!)}`
              : `Runs until ${formatISTDate(waitingPeriod.expires_on!)}`}
          </p>
        </>
      ) : (
        <p className="text-xs text-muted-foreground">Not enough information to show progress — start or expiry date is missing.</p>
      )}
    </div>
  );
}
