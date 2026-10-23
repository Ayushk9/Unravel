import type { GrievanceDraft, GrievanceDraftRequest, GrievanceRungOption } from "@/api/types";

export type DraftRung = GrievanceDraftRequest["rung"];

/** The rung to preselect: the one in the URL if it is available, else the first available one, else none. */
export function defaultRung(options: GrievanceRungOption[], requested: string | null): DraftRung | null {
  const available = options.filter((o): o is GrievanceRungOption & { rung: DraftRung } => o.available && o.rung !== "other");
  return (available.find((o) => o.rung === requested) ?? available[0])?.rung ?? null;
}

export const NO_MODEL_PARAGRAPHS = "No model-written paragraphs to check";

/**
 * The citation-precision strip as a count, never a percentage or a gauge (product rule 2).
 * Only the model's paragraphs are checked against the policy: template requests (D-47) and rules paragraphs
 * (D-48) are not counted. With no model paragraph, the server still sends citation_precision 0; it is not a
 * score, so the strip says so instead (DECISIONS.md). An unknown source counts as model text.
 */
export function confirmationSummary(paragraphs: GrievanceDraft["paragraphs"]): { confirmed: number; total: number; text: string } {
  const written = paragraphs.filter((p) => p.source !== "template" && p.source !== "rules");
  const total = written.length;
  if (total === 0) return { confirmed: 0, total: 0, text: NO_MODEL_PARAGRAPHS };
  const confirmed = written.filter((p) => p.verified).length;
  const noun = total === 1 ? "paragraph" : "paragraphs";
  const text =
    confirmed === total
      ? `${confirmed} of ${total} ${noun} confirmed against your policy.`
      : `${confirmed} of ${total} ${noun} confirmed against your policy. Check the flagged ones before sending.`;
  return { confirmed, total, text };
}
