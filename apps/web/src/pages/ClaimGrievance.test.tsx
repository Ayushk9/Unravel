// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { z } from "zod";
import type { GrievanceDraft, GrievanceRungOption } from "@/api/types";
import { ClaimGrievance } from "./ClaimGrievance";

/**
 * The grievance screen's five states (CLAUDE.md): loading, error with a
 * working retry, empty, degraded (a paragraph we couldn't confirm) and
 * abstained. apiFetch is replaced by a stand-in that answers per path; each
 * answer still goes through the endpoint's real zod schema, so these fixtures
 * are checked against the contract too. The PDF viewer is stubbed: pdf.js
 * needs a canvas, which jsdom does not have.
 */

type Handler = (path: string) => Promise<unknown>;
let handler: Handler = () => new Promise(() => {});

vi.mock("@/api/client", () => {
  class ApiError extends Error {}
  return {
    ApiError,
    apiFetch: async (path: string, options: { schema?: z.ZodType } = {}) => {
      const data = await handler(path);
      return options.schema ? options.schema.parse(data) : data;
    },
  };
});
vi.mock("@/components/primitives/DocumentViewer", () => ({ DocumentViewer: () => null }));

const CLAIM_ID = "01920000-0000-7000-8000-0000000000f3";
const POLICY_ID = "01a11b86-1640-7b09-a28f-962746188dd5";
const DOCUMENT_ID = "01a11b86-0000-7000-8000-000000000001";
const UNVERIFIED_FLAG = "We couldn't confirm this against your documents. Check or remove it before sending.";

function rung(name: GrievanceRungOption["rung"], available: boolean): GrievanceRungOption {
  return { rung: name, label: name.replaceAll("_", " "), available, reason: `Reason for ${name}.`, rule_ids: [], verified: false };
}

const claim = {
  id: CLAIM_ID,
  policy_id: POLICY_ID,
  member_id: "01920000-0000-7000-8000-000000000014",
  claim_type: "reimbursement",
  admission_type: "planned",
  hospital_name: "Navjeevan Multispeciality Hospital, Pune",
  admitted_on: "2026-04-02",
  discharged_on: "2026-04-06",
  claimed_amount: 18_500_000,
  settled_amount: null,
  current_state: "denied",
  events: [],
  deadlines: [],
  omitted_deadlines: [],
  facts: {
    diagnosis: null,
    condition_is_pre_existing: null,
    first_diagnosed_on: null,
    matched_waiting_periods: null,
    matched_exclusions: null,
    planned_room_rent_per_day: null,
  },
};

function draft(overrides: Partial<GrievanceDraft> = {}): GrievanceDraft {
  return {
    id: "01a15869-d437-7cfa-b810-ea7b80d8e0af",
    claim_id: CLAIM_ID,
    rung: "insurer_grievance_cell",
    subject: "Request to review the denial of a health insurance claim: Lakshmi Rao, policy SAMPLE-0001",
    addressee: "Grievance Redressal Officer, Star Health and Allied Insurance Co. Ltd.",
    header_lines: [
      { label: "Insured person (patient)", value: "Lakshmi Rao" },
      { label: "Plan", value: null },
    ],
    paragraphs: [
      { text: "I ask you to point me to the clause the decision relies on.", citation_ids: ["k1"], verified: true },
      { text: "My policy covers this in full regardless of any waiting period.", citation_ids: ["k1"], verified: false },
    ],
    citations: [
      {
        id: "k1",
        kind: "policy_clause",
        label: "Page 31",
        provenance: { document_id: DOCUMENT_ID, page: 31, bbox: [0.1, 0.3, 0.8, 0.33], snippet: "Pre-existing diseases ..." },
        external_url: null,
      },
    ],
    evidence_checklist: [
      { item: "Discharge summary attached", satisfied: true },
      { item: "Insurer's denial letter attached", satisfied: false },
    ],
    citation_precision: 0.5,
    closing: "I request you to review this claim and to reply to me in writing.",
    disclaimer: "This is a draft based on your documents, not legal advice.",
    letter_text: "To,\nGrievance Redressal Officer, Star Health and Allied Insurance Co. Ltd.\n...",
    missing_context: null,
    generated_at: "2026-10-20T10:00:00+00:00",
    ...overrides,
  };
}

function job(result: GrievanceDraft) {
  return { job_id: "01a15870-0000-7000-8000-000000000001", kind: "generate_grievance_draft", status: "succeeded", progress: { step: "done", percent: 100 }, result, error: null };
}

/** Answers for everything the page loads besides the rungs and the job. */
function common(path: string): Promise<unknown> | null {
  if (path === `/claims/${CLAIM_ID}`) return Promise.resolve(claim);
  if (path.startsWith("/policies/")) return new Promise(() => {}); // the viewer's default document; not needed here
  if (path.startsWith("/documents/")) return new Promise(() => {});
  return null;
}

function renderAt(url: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/claims/:id/grievance" element={<ClaimGrievance />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  handler = () => new Promise(() => {});
});
afterEach(() => cleanup());

describe("ClaimGrievance: the five states", () => {
  it("loading: shows skeletons and no rung options or Generate button yet", () => {
    handler = (path) => common(path) ?? new Promise(() => {});
    const { container } = renderAt(`/claims/${CLAIM_ID}/grievance`);

    // Three skeleton rows stand in for the three rungs (never a spinner).
    expect(container.querySelectorAll(".animate-pulse").length).toBe(3);
    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.queryByRole("button", { name: /generate/i })).toBeNull();
    expect(screen.getByText(/not legal advice/i)).toBeTruthy();
  });

  it("error: says what failed, and Try again loads the options", async () => {
    let attempts = 0;
    handler = (path) => {
      const shared = common(path);
      if (shared) return shared;
      if (path.endsWith("/grievance-rungs")) {
        attempts += 1;
        return attempts === 1 ? Promise.reject(new Error("network down")) : Promise.resolve([rung("insurer_grievance_cell", true)]);
      }
      return new Promise(() => {});
    };
    renderAt(`/claims/${CLAIM_ID}/grievance`);

    expect(await screen.findByText(/couldn't load the options/i)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByRole("radio", { name: /insurer grievance cell/i })).toBeTruthy();
  });

  it("empty: no rung fits yet, and each rung's reason is shown", async () => {
    handler = (path) =>
      common(path) ??
      (path.endsWith("/grievance-rungs")
        ? Promise.resolve([rung("insurer_grievance_cell", false), rung("irdai_bima_bharosa", false), rung("insurance_ombudsman", false)])
        : new Promise(() => {}));
    renderAt(`/claims/${CLAIM_ID}/grievance`);

    expect(await screen.findByText("No letter fits this claim yet")).toBeTruthy();
    expect(screen.getByText(/Reason for insurance_ombudsman\./)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /generate/i })).toBeNull();
  });

  it("degraded: an unconfirmed paragraph is flagged with the exact sentence, counted, and copied with the letter", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    handler = (path) =>
      common(path) ??
      (path.endsWith("/grievance-rungs")
        ? Promise.resolve([rung("insurer_grievance_cell", true), rung("irdai_bima_bharosa", false), rung("insurance_ombudsman", true)])
        : path.startsWith("/jobs/")
          ? Promise.resolve(job(draft()))
          : new Promise(() => {}));
    renderAt(`/claims/${CLAIM_ID}/grievance?rung=insurer_grievance_cell&job=01a15870-0000-7000-8000-000000000001`);

    expect(await screen.findByText(UNVERIFIED_FLAG)).toBeTruthy();
    expect(screen.getAllByText(UNVERIFIED_FLAG)).toHaveLength(1);
    expect(screen.getByText(/1 of 2 paragraphs confirmed against your policy/)).toBeTruthy();
    expect(screen.getByText("Grievance Redressal Officer, Star Health and Allied Insurance Co. Ltd.")).toBeTruthy();
    expect(screen.getByText("not recorded")).toBeTruthy();
    expect(screen.getAllByText(/Based on an unverified rule/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/%/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /copy text/i }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(draft().letter_text));
  });

  it("abstained: our own sentence, and a box for the user's own reasons, not an error", async () => {
    const abstained = draft({ paragraphs: [], citations: [], citation_precision: 0, missing_context: "The clauses we found don't give honest grounds to argue from." });
    handler = (path) =>
      common(path) ??
      (path.endsWith("/grievance-rungs")
        ? Promise.resolve([rung("insurer_grievance_cell", true)])
        : path.startsWith("/jobs/")
          ? Promise.resolve(job(abstained))
          : new Promise(() => {}));
    renderAt(`/claims/${CLAIM_ID}/grievance?job=01a15870-0000-7000-8000-000000000001`);

    expect(await screen.findByText("The clauses we found don't give honest grounds to argue from.")).toBeTruthy();
    expect(screen.getByText(/Write here why you disagree with the decision/)).toBeTruthy();
    expect(screen.queryByText(/paragraphs confirmed/)).toBeNull();
    expect(screen.queryByText(/couldn't draft the letter/i)).toBeNull();
  });
});
