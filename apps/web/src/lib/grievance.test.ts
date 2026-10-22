import { describe, expect, it } from "vitest";
import { grievanceDraftSchema, grievanceRungOptionSchema } from "@/api/schemas";
import type { GrievanceRungOption } from "@/api/types";
import { confirmationSummary, defaultRung } from "./grievance";

// The shape apps/api returns for a succeeded generate_grievance_draft job (D-43), field for field.
const serverDraft = {
  id: "01a15869-d437-7cfa-b810-ea7b80d8e0af",
  claim_id: "01920000-0000-7000-8000-0000000000f3",
  rung: "insurer_grievance_cell",
  subject: "Request to review the denial of a health insurance claim: Lakshmi Rao, policy number not recorded",
  addressee: "The Grievance Redressal Officer, Star Health and Allied Insurance",
  header_lines: [
    { label: "Insured person (patient)", value: "Lakshmi Rao" },
    { label: "Policy number", value: null },
  ],
  paragraphs: [
    { text: "Confirmed paragraph.", citation_ids: ["c-1"], verified: true, source: "model" },
    { text: "Unconfirmed paragraph.", citation_ids: ["c-1"], verified: false, source: "template" },
  ],
  citations: [
    {
      id: "c-1",
      kind: "policy_clause",
      label: "Page 31",
      provenance: { document_id: "01a15869-9a1b-78a4-ae6b-779ec0e98ac8", page: 31, bbox: [0.1, 0.3, 0.8, 0.33], snippet: "Pre-existing diseases..." },
      external_url: null,
    },
  ],
  evidence_checklist: [{ item: "Discharge summary attached", satisfied: true }],
  citation_precision: 0.5,
  closing: "I request you to review this claim and to reply to me in writing.",
  disclaimer: "This is a draft based on your documents, not legal advice.",
  letter_text: "To,\n...",
  missing_context: null,
  assessment_note: null,
  before_you_send: [],
  generated_at: "2026-10-20T10:00:00+00:00",
};

function option(rung: GrievanceRungOption["rung"], available: boolean): GrievanceRungOption {
  return { rung, label: rung, available, reason: "r", rule_ids: [], verified: false };
}

describe("grievance draft contract", () => {
  it("parses the server's draft, keeping a null header value as null", () => {
    const draft = grievanceDraftSchema.parse(serverDraft);
    expect(draft.header_lines[1]?.value).toBeNull();
    expect(draft.paragraphs.map((p) => p.verified)).toEqual([true, false]);
  });

  it("degrades an unknown rung to 'other' instead of failing (D-06)", () => {
    expect(grievanceDraftSchema.parse({ ...serverDraft, rung: "consumer_court" }).rung).toBe("other");
    expect(grievanceRungOptionSchema.parse({ ...option("insurance_ombudsman", true), rung: "new_rung" }).rung).toBe("other");
  });

  it("rejects a draft missing a D-43 field rather than rendering half a letter", () => {
    const { letter_text: _omitted, ...withoutText } = serverDraft;
    expect(grievanceDraftSchema.safeParse(withoutText).success).toBe(false);
  });
});

describe("confirmationSummary", () => {
  it("is a count, never a percentage", () => {
    const summary = confirmationSummary([
      { text: "a", citation_ids: [], verified: true, source: "model" as const },
      { text: "b", citation_ids: [], verified: true, source: "model" as const },
      { text: "c", citation_ids: [], verified: false, source: "model" as const },
    ]);
    expect(summary).toEqual({
      confirmed: 2,
      total: 3,
      text: "2 of 3 paragraphs confirmed against your policy. Check the flagged ones before sending.",
    });
    expect(summary?.text).not.toMatch(/%/);
  });

  it("counts only the model's paragraphs; template requests are not checked claims (D-47)", () => {
    const summary = confirmationSummary([
      { text: "a", citation_ids: [], verified: true, source: "model" as const },
      { text: "Please tell me the clause.", citation_ids: [], verified: false, source: "template" as const },
    ]);
    expect(summary?.text).toBe("1 of 1 paragraph confirmed against your policy.");
    expect(confirmationSummary([{ text: "t", citation_ids: [], verified: false, source: "template" as const }])).toBeNull();
  });

  it("says nothing when there are no paragraphs (the abstention card speaks instead)", () => {
    expect(confirmationSummary([])).toBeNull();
  });

  it("has no warning when every paragraph is confirmed", () => {
    expect(confirmationSummary([{ text: "a", citation_ids: [], verified: true, source: "model" as const }])?.text).toBe("1 of 1 paragraph confirmed against your policy.");
  });
});

describe("defaultRung", () => {
  const options = [option("insurer_grievance_cell", true), option("irdai_bima_bharosa", false), option("insurance_ombudsman", true)];

  it("prefers the rung in the URL when it is available", () => {
    expect(defaultRung(options, "insurance_ombudsman")).toBe("insurance_ombudsman");
  });

  it("never preselects an unavailable rung", () => {
    expect(defaultRung(options, "irdai_bima_bharosa")).toBe("insurer_grievance_cell");
    expect(defaultRung([option("insurer_grievance_cell", false)], null)).toBeNull();
  });
});
