/**
 * D-12 exists because naive date arithmetic produces off-by-one-day errors on
 * exactly the deadlines that matter most. Two rules followed here:
 * - ISODate ("YYYY-MM-DD") comparisons use plain string comparison, which is
 *   correct for zero-padded ISO dates and sidesteps Date-parsing timezone
 *   pitfalls entirely.
 * - ISODateTime arithmetic stays in UTC milliseconds internally and is
 *   always re-serialised with an explicit +05:30 offset (IST has no DST, so
 *   this is safe), never through Date#toISOString() which would emit "Z".
 */

const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000;

export function nowIso(): string {
  return toIstIso(Date.now());
}

export function toIstIso(epochMs: number): string {
  const ist = new Date(epochMs + IST_OFFSET_MS);
  const pad = (n: number, len = 2) => String(n).padStart(len, "0");
  const y = ist.getUTCFullYear();
  const mo = pad(ist.getUTCMonth() + 1);
  const d = pad(ist.getUTCDate());
  const h = pad(ist.getUTCHours());
  const mi = pad(ist.getUTCMinutes());
  const s = pad(ist.getUTCSeconds());
  return `${y}-${mo}-${d}T${h}:${mi}:${s}+05:30`;
}

export function addDaysToIso(isoDateTime: string, days: number): string {
  const epochMs = new Date(isoDateTime).getTime();
  return toIstIso(epochMs + days * 24 * 60 * 60 * 1000);
}

/** Whole days between `now` and `dueAtIso` — negative once the deadline has passed. */
export function daysRemaining(dueAtIso: string): number {
  const dueMs = new Date(dueAtIso).getTime();
  const nowMs = Date.now();
  return Math.floor((dueMs - nowMs) / (24 * 60 * 60 * 1000));
}

/** Approximate whole calendar months between two ISODate ("YYYY-MM-DD") strings — for explanatory prose only, never for the pass/fail comparison itself (use plain string comparison against expires_on for that). */
export function approxMonthsBetween(fromIsoDate: string, toIsoDate: string): number {
  const [y1, m1] = fromIsoDate.split("-").map(Number) as [number, number];
  const [y2, m2] = toIsoDate.split("-").map(Number) as [number, number];
  return (y2 - y1) * 12 + (m2 - m1);
}

export function formatDMY(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number) as [number, number, number];
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${d} ${months[m - 1]} ${y}`;
}

/** `months` calendar months after an ISODate, clamped to a shorter month's last day (31 Jan + 1 = 28/29 Feb), as the backend does. */
export function addMonthsIso(isoDate: string, months: number): string {
  const [y, m, d] = isoDate.split("-").map(Number) as [number, number, number];
  const total = y * 12 + (m - 1) + months;
  const year = Math.floor(total / 12);
  const month = (total % 12) + 1;
  const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${year}-${pad(month)}-${pad(Math.min(d, lastDay))}`;
}

/** Today's date in India, "YYYY-MM-DD". */
export function todayIst(): string {
  return nowIso().slice(0, 10);
}
