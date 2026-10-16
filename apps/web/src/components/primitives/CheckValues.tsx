import type { CheckValue } from "@/api/types";
import { formatISTDate } from "@/lib/formatDate";
import { Money } from "./Money";

/**
 * D-36: the values a check's sentence was rendered from, shown as a plain
 * list so a reader can follow the arithmetic. Nothing here is recomputed:
 * every number is the server's.
 *
 * Keys are rule-specific. A disease-specific check prefixes them with the
 * condition ("cataract: waiting_months"), so the label is read from the part
 * after the last ": ". Unknown keys still render, with the key made readable.
 */

const LABELS: Record<string, string> = {
  policy_start: "Policy start date",
  first_inception_date: "Continuous cover started",
  waiting_months: "Waiting period (months)",
  waiting_period_ends: "Waiting period ends",
  admitted_on: "Admitted on",
  elapsed_months: "Months into the period",
  elapsed_days: "…and days",
  remaining_months: "Months still to run",
  remaining_days: "…and days",
  condition_is_pre_existing: "You said it is pre-existing",
  first_diagnosed_on: "First diagnosed on",
  matched_waiting_periods: "Listed conditions you chose",
  matched_exclusions: "Exclusions you chose",
  room_rent_per_day: "Room rent per day",
  room_rent_cap_per_day: "Policy's room rent cap per day",
  excess_per_day: "Over the cap, per day",
  deadline_hours: "Deadline to tell the insurer (hours)",
  intimation_due_by: "Insurer to be told by",
  intimated_on: "Insurer told on",
  days_late: "Days late",
  claimed_amount: "Amount claimed",
  sum_insured: "Sum insured",
  amount_over: "Over the sum insured",
};

// Integer paise: rendered only through <Money>.
const MONEY_KEYS = new Set(["room_rent_per_day", "room_rent_cap_per_day", "excess_per_day", "claimed_amount", "sum_insured", "amount_over"]);
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function readableKey(key: string): string {
  const text = key.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function Value({ name, value }: { name: string; value: CheckValue }) {
  if (value === null) return <span className="text-muted-foreground">Not known</span>;
  if (typeof value === "boolean") return <span>{value ? "Yes" : "No"}</span>;
  if (typeof value === "number" && MONEY_KEYS.has(name)) return <Money value={value} />;
  if (typeof value === "string" && ISO_DATE.test(value)) return <span className="font-tabular">{formatISTDate(value)}</span>;
  return <span className="font-tabular">{String(value)}</span>;
}

export interface CheckValuesProps {
  values: Record<string, CheckValue>;
  className?: string;
}

export function CheckValues({ values, className }: CheckValuesProps) {
  const entries = Object.entries(values);
  if (entries.length === 0) return null;

  return (
    <dl className={`grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs ${className ?? ""}`}>
      {entries.map(([key, value]) => {
        const split = key.lastIndexOf(": ");
        const prefix = split >= 0 ? key.slice(0, split) : null;
        const name = split >= 0 ? key.slice(split + 2) : key;
        const label = LABELS[name] ?? readableKey(name);
        return (
          <div key={key} className="contents">
            <dt className="text-muted-foreground">{prefix ? `${prefix}: ${label}` : label}</dt>
            <dd className="text-foreground">
              <Value name={name} value={value} />
            </dd>
          </div>
        );
      })}
    </dl>
  );
}
