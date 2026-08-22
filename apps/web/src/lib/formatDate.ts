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
