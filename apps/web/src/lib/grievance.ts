import type { GrievanceDraft, GrievanceDraftRequest, GrievanceRungOption } from "@/api/types";

export type DraftRung = GrievanceDraftRequest["rung"];

/** The rung to preselect: the one in the URL if it is available, else the first available one, else none. */
export function defaultRung(options: GrievanceRungOption[], requested: string | null): DraftRung | null {
  const available = options.filter((o): o is GrievanceRungOption & { rung: DraftRung } => o.available && o.rung !== "other");
  return (available.find((o) => o.rung === requested) ?? available[0])?.rung ?? null;
}

/**
 * The citation-precision strip as a count, never a percentage or a gauge (product rule 2).
 * Null when there are no paragraphs: the abstention card says why instead.
 */
export function confirmationSummary(paragraphs: GrievanceDraft["paragraphs"]): { confirmed: number; total: number; text: string } | null {
  const total = paragraphs.length;
  if (total === 0) return null;
  const confirmed = paragraphs.filter((p) => p.verified).length;
  const noun = total === 1 ? "paragraph" : "paragraphs";
  const text =
    confirmed === total
      ? `${confirmed} of ${total} ${noun} confirmed against your policy.`
      : `${confirmed} of ${total} ${noun} confirmed against your policy. Check the flagged ones before sending.`;
  return { confirmed, total, text };
}
