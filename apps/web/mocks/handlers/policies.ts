import { http, HttpResponse } from "msw";
import type { FieldCorrectionRequest, JobAccepted, Policy, PolicyCreateRequest, QuestionAnswerResult, QuestionRequest } from "@/api/types";
import * as db from "../db";
import { errorResponse, notFound, plainReadDelay, requireAuth } from "../utils";
import { applyGlobalScenarios, getScenarios } from "../scenarios";

/** Dev-toolbar "low-confidence extraction" scenario: downgrades every extracted field so a screen can demo the review/unverified treatment on demand, regardless of which real policy is open. */
function withLowConfidenceOverride(policy: Policy): Policy {
  if (!getScenarios().forceLowConfidence || !policy.coverage_profile) return policy;
  const clone = structuredClone(policy);
  const profile = clone.coverage_profile!;
  for (const field of [profile.sum_insured, profile.co_pay_percent, profile.intimation_deadline_hours]) {
    field.confidence = "low";
    field.user_confirmed = false;
  }
  for (const subLimit of profile.sub_limits) {
    subLimit.cap_amount.confidence = "low";
    subLimit.cap_amount.user_confirmed = false;
  }
  for (const waitingPeriod of profile.waiting_periods) {
    waitingPeriod.months.confidence = "low";
    waitingPeriod.months.user_confirmed = false;
  }
  for (const exclusion of profile.exclusions) {
    exclusion.confidence = "low";
    exclusion.user_confirmed = false;
  }
  return clone;
}

export const policiesHandlers = [
  http.get("*/api/v1/policies", async ({ request }) => {
    const authError = requireAuth(request);
    if (authError) return authError;
    const scenario = await applyGlobalScenarios();
    if (scenario.shortCircuit) return scenario.shortCircuit;
    await plainReadDelay();

    const list = getScenarios().forceEmpty ? [] : db.listPolicies().map(withLowConfidenceOverride);
    return HttpResponse.json(list);
  }),

  http.post("*/api/v1/policies", async ({ request }) => {
    const authError = requireAuth(request);
    if (authError) return authError;
    await plainReadDelay();

    const body = (await request.json()) as PolicyCreateRequest;
    const existing = db.listPolicies().find((p) => p.source_document_id === body.source_document_id);
    if (existing) return HttpResponse.json(existing, { status: 200 });

    const document = db.getDocument(body.source_document_id);
    if (!document || document.parse_status !== "parsed") {
      return errorResponse(409, {
        code: "document_not_parsed",
        message: "This document hasn't finished parsing into a policy yet.",
      });
    }
    return errorResponse(409, {
      code: "no_draft_policy",
      message: "No parsed policy draft is attached to this document.",
    });
  }),

  http.get("*/api/v1/policies/:id", async ({ request, params }) => {
    const authError = requireAuth(request);
    if (authError) return authError;
    const scenario = await applyGlobalScenarios();
    if (scenario.shortCircuit) return scenario.shortCircuit;
    await plainReadDelay();

    const policy = db.getPolicy(params.id as string);
    if (!policy) return notFound("No policy with that id belongs to your household.");
    return HttpResponse.json(withLowConfidenceOverride(policy));
  }),

  http.patch("*/api/v1/policies/:id/coverage-profile/fields/:fieldPath", async ({ request, params }) => {
    const authError = requireAuth(request);
    if (authError) return authError;
    await plainReadDelay();

    const body = (await request.json()) as FieldCorrectionRequest;
    const result = db.patchCoverageField(params.id as string, params.fieldPath as string, body.value, body.user_confirmed);

    if (!result.ok) {
      if (result.reason === "policy_not_found") return notFound("No policy with that id belongs to your household.");
      if (result.reason === "profile_not_ready") {
        return errorResponse(409, { code: "profile_not_ready", message: "This policy's coverage profile isn't ready yet." });
      }
      return errorResponse(422, {
        code: "validation_error",
        message: "That field path isn't correctable.",
        field_errors: [{ field: "field_path", message: `Unknown or non-correctable field: ${params.fieldPath}` }],
      });
    }
    return HttpResponse.json(result.policy);
  }),

  http.post("*/api/v1/policies/:id/questions", async ({ request, params }) => {
    const authError = requireAuth(request);
    if (authError) return authError;
    const scenario = await applyGlobalScenarios();
    if (scenario.shortCircuit) return scenario.shortCircuit;

    const policy = db.getPolicy(params.id as string);
    if (!policy) return notFound("No policy with that id belongs to your household.");

    const body = (await request.json()) as QuestionRequest;
    const forceAbstain = getScenarios().forceAbstention;

    const job = db.createJob("answer_question", [3000, 6000], (): QuestionAnswerResult => {
      if (forceAbstain || !policy.coverage_profile) {
        return {
          answer: "",
          citations: [],
          abstained: true,
          missing_context: "Your policy documents don't answer this. The clause may be in a document you haven't uploaded.",
        };
      }
      const roomRent = policy.coverage_profile.sub_limits.find((s) => s.category === "room_rent");
      return {
        answer: roomRent
          ? `Your room rent is capped at the amount shown in your policy's sub-limits table. Choosing a room above that cap can trigger a proportionate deduction across your whole bill.`
          : `Based on your policy's coverage profile, this depends on the specific clause — see the cited source.`,
        citations: [
          {
            id: "cite-1",
            kind: "policy_clause",
            label: policy.product_name,
            provenance: roomRent?.cap_amount.provenance ?? null,
            external_url: null,
          },
        ],
        abstained: false,
        missing_context: null,
      };
    });

    const responseBody: JobAccepted = { job_id: job.job_id, kind: job.kind, status: "queued" };
    void body; // question text isn't used to branch the mock's canned answer
    return HttpResponse.json(responseBody, { status: 202 });
  }),
];
