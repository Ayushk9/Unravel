import { http, HttpResponse } from "msw";
import type {
  ClaimFacts,
  BillValidationReport,
  Claim,
  ClaimCreateRequest,
  ClaimEventRequest,
  CompletenessReport,
  DocumentType,
  GrievanceDraft,
  GrievanceDraftRequest,
  GrievanceRungOption,
  JobAccepted,
} from "@/api/types";
import * as db from "../db";
import { deniedClaimBillFlags, deniedClaimBillLineItems, deniedClaimBillTotalAtRisk, deniedClaimBillTotalBilled, ids } from "../fixtures";
import { NO_FACTS } from "../fixtures/claims";
import { computeDeadlines } from "../deadlines";
import { computeEligibility } from "../eligibility";
import { errorResponse, genId, notFound, plainReadDelay, requireAuth } from "../utils";
import { applyGlobalScenarios, getScenarios } from "../scenarios";

const MOCK_DISCLAIMER = "This is a draft based on your documents, not legal advice. Check every statement before you send it; you send it yourself.";
const MOCK_UNCONFIRMED = "[NOT CONFIRMED AGAINST YOUR POLICY. Check or remove before sending.]";
const MOCK_ADDRESSEE: Record<GrievanceDraft["rung"], string> = {
  insurer_grievance_cell: "The Grievance Redressal Officer, your insurer",
  irdai_bima_bharosa: "Insurance Regulatory and Development Authority of India (IRDAI), through the Bima Bharosa grievance portal",
  insurance_ombudsman: "The Insurance Ombudsman (the office covering your area)",
  other: "Your insurer",
};

/**
 * Registered once at module load — see documents.ts's parse_document resolver for why this can't be a closure passed to db.createJob.
 * Mirrors the real D-43 shape: the header is built from the claim's own fields, and one paragraph is
 * deliberately unverified so the flagged state (product rule 4) is always on screen in mock mode.
 */
db.registerJobResolver("generate_grievance_draft", (params): GrievanceDraft => {
  const { claimId, rung } = params as { claimId: string; rung: GrievanceDraft["rung"] };
  const claim = db.getClaim(claimId);
  const policy = claim ? db.getPolicy(claim.policy_id) : undefined;
  const eligibility = claim && policy ? computeEligibility(claim, policy) : null;
  const pedCheck = eligibility?.checks.find((c) => c.id === "ped_waiting_period");
  const denied = [...(claim?.events ?? [])].reverse().find((e) => e.to_state === "denied");

  const header_lines = [
    { label: "Hospital", value: claim?.hospital_name ?? null },
    { label: "Policy number", value: policy?.policy_number ?? null },
    { label: "Admitted on", value: claim?.admitted_on ?? null },
    { label: "Discharged on", value: claim?.discharged_on ?? null },
    { label: "Claim denied on", value: denied ? denied.occurred_at.slice(0, 10) : null },
    { label: "Reason for denial, as recorded", value: denied?.note ? `\u201c${denied.note}\u201d` : null },
  ];
  const paragraphs = [
    {
      text: "I ask you to point me to the exact clause of my policy that the decision relies on, and to explain how it applies to this admission.",
      citation_ids: pedCheck ? ["cite-policy"] : [],
      verified: Boolean(pedCheck),
    },
    {
      text: "My policy covers this treatment in full regardless of any waiting period.",
      citation_ids: pedCheck ? ["cite-policy"] : [],
      verified: false,
    },
  ];
  const subject = `Request to review the denial of a health insurance claim: ${claim?.hospital_name ?? "the hospital"}`;
  const closing = "I request you to review this claim and to reply to me in writing.\n\nYours faithfully,\n\n(Your name, signature, address and phone number)";
  const letter_text = [
    `To,\n${MOCK_ADDRESSEE[rung]}`,
    `Subject: ${subject}`,
    header_lines.map((l) => `${l.label}: ${l.value ?? "not recorded"}`).join("\n"),
    "Dear Sir or Madam,",
    ...paragraphs.map((p) => (p.verified ? p.text : `${MOCK_UNCONFIRMED}\n${p.text}`)),
    closing,
    `---\n${MOCK_DISCLAIMER}`,
  ].join("\n\n");

  return {
    id: genId("grievance"),
    claim_id: claimId,
    rung,
    subject,
    addressee: MOCK_ADDRESSEE[rung],
    header_lines,
    paragraphs,
    citations: pedCheck
      ? [{ id: "cite-policy", kind: "policy_clause", label: "Page 31", provenance: pedCheck.governing_clause ?? null, external_url: null }]
      : [],
    evidence_checklist: [
      { item: "Discharge summary attached", satisfied: true },
      { item: "Itemised hospital bill attached", satisfied: true },
      { item: "Insurer's denial letter attached", satisfied: false },
    ],
    citation_precision: paragraphs.filter((p) => p.verified).length / paragraphs.length,
    closing,
    disclaimer: MOCK_DISCLAIMER,
    letter_text,
    missing_context: null,
    generated_at: new Date().toISOString(),
  };
});

/** D-43 mock: every rung is offered after a denial or an escalation, marked unverified like the real rule file. */
function mockRungs(claim: Claim): GrievanceRungOption[] {
  const open = claim.current_state === "denied" || claim.current_state === "escalated";
  const note = "This is based on a rule that has not yet been checked against its source.";
  const rows: [GrievanceRungOption["rung"], string, string][] = [
    ["insurer_grievance_cell", "Insurer's grievance cell", "Writing to the insurer's grievance cell is usually the first step."],
    ["irdai_bima_bharosa", "IRDAI Bima Bharosa", "Bima Bharosa usually expects you to have complained to the insurer first."],
    ["insurance_ombudsman", "Insurance Ombudsman", "The Ombudsman usually expects you to have written to the insurer first."],
  ];
  return rows.map(([rung, label, reason]) => ({
    rung,
    label,
    available: open,
    reason: open ? `${reason} ${note}` : "Available once the claim has been denied, or you have written to the insurer's grievance cell.",
    rule_ids: [],
    verified: false,
  }));
}

function withComputedDeadlines(claim: Claim): Claim {
  // omitted_deadlines is set here, not read from the stored claim, so claims
  // persisted to sessionStorage before the field existed still validate.
  return { ...claim, deadlines: computeDeadlines(claim), omitted_deadlines: [] };
}

const REQUIRED_DOCUMENTS: Record<string, DocumentType[]> = {
  reimbursement: ["discharge_summary", "itemised_bill", "payment_receipt", "id_proof"],
  cashless: ["discharge_summary", "id_proof"],
};

export const claimsHandlers = [
  http.get("*/api/v1/claims", async ({ request }) => {
    const authError = requireAuth(request);
    if (authError) return authError;
    const scenario = await applyGlobalScenarios();
    if (scenario.shortCircuit) return scenario.shortCircuit;
    await plainReadDelay();

    const list = getScenarios().forceEmpty ? [] : db.listClaims().map(withComputedDeadlines);
    return HttpResponse.json(list);
  }),

  http.post("*/api/v1/claims", async ({ request }) => {
    const authError = requireAuth(request);
    if (authError) return authError;
    await plainReadDelay();

    const body = (await request.json()) as ClaimCreateRequest;
    if (!db.getPolicy(body.policy_id)) {
      return errorResponse(422, {
        code: "validation_error",
        message: "That policy doesn't belong to your household.",
        field_errors: [{ field: "policy_id", message: "Unknown policy." }],
      });
    }

    const claimId = genId("claim");
    const now = new Date().toISOString();
    const claim: Claim = {
      id: claimId,
      policy_id: body.policy_id,
      member_id: body.member_id,
      claim_type: body.claim_type,
      admission_type: body.admission_type,
      hospital_name: body.hospital_name,
      admitted_on: body.admitted_on,
      discharged_on: body.discharged_on,
      claimed_amount: body.claimed_amount,
      settled_amount: null,
      current_state: "intimated",
      events: [{ id: genId("event"), claim_id: claimId, from_state: null, to_state: "intimated", occurred_at: now, note: "Claim intimated via app", source: "user" }],
      deadlines: [],
      omitted_deadlines: [],
      facts: { ...NO_FACTS },
    };
    db.addClaim(claim);
    return HttpResponse.json(withComputedDeadlines(claim), { status: 201 });
  }),

  http.get("*/api/v1/claims/:id", async ({ request, params }) => {
    const authError = requireAuth(request);
    if (authError) return authError;
    const scenario = await applyGlobalScenarios();
    if (scenario.shortCircuit) return scenario.shortCircuit;
    await plainReadDelay();

    const claim = db.getClaim(params.id as string);
    if (!claim) return notFound("No claim with that id belongs to your household.");
    return HttpResponse.json(withComputedDeadlines(claim));
  }),

  http.post("*/api/v1/claims/:id/events", async ({ request, params }) => {
    const authError = requireAuth(request);
    if (authError) return authError;
    await plainReadDelay();

    const claim = db.getClaim(params.id as string);
    if (!claim) return notFound("No claim with that id belongs to your household.");

    // Dev-toolbar-only: forces the 409 path deterministically, regardless of
    // which target state was actually picked, so the inline allowed-states
    // recovery UI is reachable without hunting for a genuinely illegal move.
    if (getScenarios().forceIllegalTransition) {
      return errorResponse(409, {
        code: "illegal_transition",
        message: "That transition isn't allowed from the claim's current state. (Forced from the dev toolbar.)",
        field_errors: db.CLAIM_TRANSITIONS[claim.current_state].map((state) => ({ field: "to_state", message: state })),
      });
    }

    const body = (await request.json()) as ClaimEventRequest;
    const result = db.appendClaimEvent(params.id as string, body.to_state, body.occurred_at, body.note);

    if (!result.ok) {
      if (result.reason === "not_found") return notFound("No claim with that id belongs to your household.");
      return errorResponse(409, {
        code: "illegal_transition",
        message: "That transition isn't allowed from the claim's current state.",
        field_errors: result.allowed.map((state) => ({ field: "to_state", message: state })),
      });
    }
    return HttpResponse.json(withComputedDeadlines(result.claim));
  }),

  // D-37: a full replacement of the claim's facts.
  http.put("*/api/v1/claims/:id/facts", async ({ request, params }) => {
    const authError = requireAuth(request);
    if (authError) return authError;
    await plainReadDelay();

    const body = (await request.json()) as ClaimFacts;
    const result = db.setClaimFacts(params.id as string, body);
    if (!result.ok) {
      if (result.reason === "not_found") return notFound("No claim with that id belongs to your household.");
      return errorResponse(422, {
        code: "validation_error",
        message: "Those claim facts aren't valid.",
        field_errors: [{ field: result.field, message: result.message }],
      });
    }
    return HttpResponse.json(withComputedDeadlines(result.claim));
  }),

  http.post("*/api/v1/claims/:id/eligibility", async ({ request, params }) => {
    const authError = requireAuth(request);
    if (authError) return authError;
    const scenario = await applyGlobalScenarios();
    if (scenario.shortCircuit) return scenario.shortCircuit;
    await plainReadDelay();

    const claim = db.getClaim(params.id as string);
    if (!claim) return notFound("No claim with that id belongs to your household.");
    const policy = db.getPolicy(claim.policy_id);
    if (!policy) return notFound("This claim's policy is missing.");

    return HttpResponse.json(computeEligibility(claim, policy));
  }),

  http.post("*/api/v1/claims/:id/completeness", async ({ request, params }) => {
    const authError = requireAuth(request);
    if (authError) return authError;
    const scenario = await applyGlobalScenarios();
    if (scenario.shortCircuit) return scenario.shortCircuit;
    await plainReadDelay();

    const claim = db.getClaim(params.id as string);
    if (!claim) return notFound("No claim with that id belongs to your household.");

    const required = REQUIRED_DOCUMENTS[claim.claim_type] ?? REQUIRED_DOCUMENTS.reimbursement!;
    const present = [
      ...new Set(
        db
          .documentsForClaim(claim.id)
          .map((d) => d.detected_type.value)
          .filter((t): t is DocumentType => t !== null),
      ),
    ];
    const missing = required.filter((t) => !present.includes(t));

    const report: CompletenessReport = {
      claim_id: claim.id,
      required,
      present,
      missing,
      advisory_note:
        missing.length === 0
          ? "All the documents your claim type usually needs are present."
          : `Missing ${missing.length} document${missing.length === 1 ? "" : "s"} before this claim looks complete.`,
      required_details: required.map((type) => ({
        type,
        description: "Usually needed for this type of claim.",
        where_to_get: "Ask the hospital or your insurer.",
        source: { document: "Mock checklist", section: null, url: null },
      })),
      verified: false,
    };
    return HttpResponse.json(report);
  }),

  http.post("*/api/v1/claims/:id/bill-validation", async ({ request, params }) => {
    const authError = requireAuth(request);
    if (authError) return authError;
    const scenario = await applyGlobalScenarios();
    if (scenario.shortCircuit) return scenario.shortCircuit;
    await plainReadDelay();

    const claim = db.getClaim(params.id as string);
    if (!claim) return notFound("No claim with that id belongs to your household.");

    const billDocument = db.documentsForClaim(claim.id).find((d) => d.detected_type.value === "itemised_bill");
    if (!billDocument) {
      return errorResponse(409, {
        code: "bill_not_parsed",
        message: "This claim doesn't have a parsed itemised bill yet.",
      });
    }

    const isDeniedClaimFixture = claim.id === ids.claim.denied;
    const report: BillValidationReport = isDeniedClaimFixture
      ? {
          claim_id: claim.id,
          line_items: deniedClaimBillLineItems,
          flags: deniedClaimBillFlags,
          total_billed: deniedClaimBillTotalBilled,
          total_at_risk: deniedClaimBillTotalAtRisk,
          generated_at: new Date().toISOString(),
        }
      : {
          claim_id: claim.id,
          line_items: [
            {
              id: genId("bill-item"),
              description: "Hospitalisation charges",
              quantity: 1,
              rate: claim.claimed_amount ?? 0,
              amount: claim.claimed_amount ?? 0,
              provenance: null,
            },
          ],
          flags: [],
          total_billed: claim.claimed_amount ?? 0,
          total_at_risk: 0,
          generated_at: new Date().toISOString(),
        };
    return HttpResponse.json(report);
  }),

  http.get("*/api/v1/claims/:id/grievance-rungs", async ({ request, params }) => {
    const authError = requireAuth(request);
    if (authError) return authError;
    const scenario = await applyGlobalScenarios();
    if (scenario.shortCircuit) return scenario.shortCircuit;
    await plainReadDelay();

    const claim = db.getClaim(params.id as string);
    if (!claim) return notFound("No claim with that id belongs to your household.");
    return HttpResponse.json(mockRungs(claim));
  }),

  http.post("*/api/v1/claims/:id/grievance-drafts", async ({ request, params }) => {
    const authError = requireAuth(request);
    if (authError) return authError;
    const scenario = await applyGlobalScenarios();
    if (scenario.shortCircuit) return scenario.shortCircuit;

    const idempotencyKey = request.headers.get("Idempotency-Key");
    if (!idempotencyKey) {
      return errorResponse(422, {
        code: "validation_error",
        message: "Idempotency-Key is required on this endpoint.",
        field_errors: [{ field: "Idempotency-Key", message: "This header is required." }],
      });
    }
    const replay = db.getIdempotentResponse(idempotencyKey);
    if (replay) return HttpResponse.json(replay.body, { status: replay.status });

    const claim = db.getClaim(params.id as string);
    if (!claim) return notFound("No claim with that id belongs to your household.");

    const body = (await request.json()) as GrievanceDraftRequest;
    const job = db.createJob("generate_grievance_draft", [20_000, 30_000], { claimId: claim.id, rung: body.rung });

    const responseBody: JobAccepted = { job_id: job.job_id, kind: job.kind, status: "queued" };
    db.storeIdempotentResponse(idempotencyKey, 202, responseBody);
    return HttpResponse.json(responseBody, { status: 202 });
  }),
];
