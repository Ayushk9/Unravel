import { http, HttpResponse } from "msw";
import type {
  BillValidationReport,
  Claim,
  ClaimCreateRequest,
  ClaimEventRequest,
  CompletenessReport,
  DocumentType,
  GrievanceDraft,
  GrievanceDraftRequest,
  JobAccepted,
} from "@/api/types";
import * as db from "../db";
import { deniedClaimBillFlags, deniedClaimBillLineItems, deniedClaimBillTotalAtRisk, deniedClaimBillTotalBilled, ids } from "../fixtures";
import { computeDeadlines } from "../deadlines";
import { computeEligibility } from "../eligibility";
import { errorResponse, genId, notFound, plainReadDelay, requireAuth } from "../utils";
import { applyGlobalScenarios, getScenarios } from "../scenarios";

/** Registered once at module load — see documents.ts's parse_document resolver for why this can't be a closure passed to db.createJob. */
db.registerJobResolver("generate_grievance_draft", (params): GrievanceDraft => {
  const { claimId, rung } = params as { claimId: string; rung: GrievanceDraft["rung"] };
  const claim = db.getClaim(claimId);
  const policy = claim ? db.getPolicy(claim.policy_id) : undefined;
  const eligibility = claim && policy ? computeEligibility(claim, policy) : null;
  const pedCheck = eligibility?.checks.find((c) => c.id === "ped_waiting_period");

  return {
    id: genId("grievance"),
    claim_id: claimId,
    rung,
    subject: `Grievance regarding denial of claim at ${claim?.hospital_name ?? "the hospital"}`,
    paragraphs: [
      {
        text: `I am writing regarding the denial of my claim for hospitalisation at ${claim?.hospital_name} from ${claim?.admitted_on} to ${claim?.discharged_on}.`,
        citation_ids: [],
        verified: true,
      },
      {
        text: pedCheck
          ? pedCheck.explanation
          : "The denial ground cited does not, in my assessment, apply to the facts of this admission.",
        citation_ids: pedCheck ? ["cite-policy"] : [],
        verified: Boolean(pedCheck),
      },
      {
        // Deliberately unverified — every draft should demonstrate the
        // "flag unsupported sentences, never silently" rule (product
        // rule 4), not just the happy path.
        text: "Similar denials on this ground have previously been overturned by the Insurance Ombudsman.",
        citation_ids: ["cite-award"],
        verified: false,
      },
    ],
    citations: [
      { id: "cite-policy", kind: "policy_clause", label: policy?.product_name ?? "Policy", provenance: pedCheck?.governing_clause ?? null, external_url: null },
      { id: "cite-award", kind: "ombudsman_award", label: "Similar PED-denial precedent", provenance: null, external_url: null },
    ],
    evidence_checklist: [
      { item: "Discharge summary", satisfied: true },
      { item: "Itemised bill", satisfied: true },
      { item: "Denial letter", satisfied: true },
    ],
    citation_precision: 0.67,
  };
});

function withComputedDeadlines(claim: Claim): Claim {
  return { ...claim, deadlines: computeDeadlines(claim) };
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
