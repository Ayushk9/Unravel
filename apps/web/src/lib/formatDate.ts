/**
 * Display is IST throughout the UI (docs/API_DECISIONS.md D-12), regardless
 * of the viewer's device timezone — so this always pins Asia/Kolkata rather
 * than relying on the browser's local zone.
 */
const istDateFormatter = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata",
  day: "numeric",
  month: "short",
  year: "numeric",
});

export function formatISTDate(iso: string): string {
  return istDateFormatter.format(new Date(iso));
}

const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000;

function epochToIsoIst(epochMs: number): string {
  const ist = new Date(epochMs + IST_OFFSET_MS);
  const pad = (n: number) => String(n).padStart(2, "0");
  const y = ist.getUTCFullYear();
  const mo = pad(ist.getUTCMonth() + 1);
  const d = pad(ist.getUTCDate());
  const h = pad(ist.getUTCHours());
  const mi = pad(ist.getUTCMinutes());
  const s = pad(ist.getUTCSeconds());
  return `${y}-${mo}-${d}T${h}:${mi}:${s}+05:30`;
}

/** Current instant serialized with the +05:30 offset (D-12) — never `Date#toISOString()`, which emits "Z". Used when the client appends a claim event. */
export function nowIsoIst(): string {
  return epochToIsoIst(Date.now());
}

/** Interprets a `datetime-local` input's value as IST wall-clock time (the UI's only timezone) and appends the offset directly — no Date-based conversion, same reasoning as mocks/dateMath.ts. */
export function localDateTimeToIsoIst(localValue: string): string {
  return `${localValue}:00+05:30`;
}
