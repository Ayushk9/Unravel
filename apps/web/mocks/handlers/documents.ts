import { http, HttpResponse } from "msw";
import type { JobAccepted, ParseDocumentResult, Policy } from "@/api/types";
import * as db from "../db";
import { policyById, retailPolicy } from "../fixtures";
import { errorResponse, genId, notFound, paginate, plainReadDelay, requireAuth } from "../utils";
import { applyGlobalScenarios } from "../scenarios";

const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
const ALLOWED_MIME_TYPES = ["application/pdf", "image/jpeg", "image/png", "image/heic", "image/webp"];

export const documentsHandlers = [
  http.post("*/api/v1/documents", async ({ request }) => {
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
    if (replay) {
      return HttpResponse.json(replay.body, { status: replay.status });
    }

    const formData = await request.formData();
    const file = formData.get("file");
    const claimId = (formData.get("claim_id") as string | null) || null;

    if (!(file instanceof File)) {
      return errorResponse(422, {
        code: "validation_error",
        message: "A file is required.",
        field_errors: [{ field: "file", message: "This field is required." }],
      });
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      return errorResponse(413, { code: "file_too_large", message: "Upload exceeds 25 MB." });
    }
    if (!ALLOWED_MIME_TYPES.includes(file.type)) {
      return errorResponse(422, {
        code: "validation_error",
        message: "Only PDF and common image types are accepted.",
        field_errors: [{ field: "file", message: `Unsupported file type: ${file.type || "unknown"}` }],
      });
    }

    const documentId = genId("doc");
    const job = db.createJob("parse_document", [4000, 8000], (): ParseDocumentResult => {
      const looksLikePolicy = !claimId; // policy uploads happen outside a claim; claim uploads are bills/discharge summaries/etc.
      const detectedType = looksLikePolicy ? "policy_schedule" : "itemised_bill";

      db.addDocument({
        id: documentId,
        file_name: file.name,
        mime_type: file.type,
        page_count: looksLikePolicy ? 4 : 2,
        uploaded_at: new Date().toISOString(),
        claim_id: claimId,
        detected_type: {
          value: detectedType,
          confidence: "high",
          provenance: { document_id: documentId, page: 1, bbox: null, snippet: null },
          user_confirmed: false,
        },
        parse_status: "parsed",
        parse_error: null,
        deleted_at: null,
      });

      let policyId: string | null = null;
      if (looksLikePolicy) {
        // Reuse the retail policy's extraction shape (including its
        // deliberately low-confidence room-rent cap — see brief §6.1's
        // upload-review scenario) so the review screen has something
        // realistic to demonstrate, regardless of what was actually
        // uploaded in the mock.
        const template = policyById(retailPolicy.id);
        if (template?.coverage_profile) {
          policyId = genId("policy");
          const newPolicy: Policy = {
            ...structuredClone(template),
            id: policyId,
            policy_number: `NEW/${genId("pol").toUpperCase()}`,
            source_document_id: documentId,
          };
          if (newPolicy.coverage_profile) newPolicy.coverage_profile.policy_id = policyId;
          db.addPolicy(newPolicy);
        }
      }

      return { document_id: documentId, policy_id: policyId };
    });

    const body: JobAccepted = { job_id: job.job_id, kind: job.kind, status: "queued" };
    db.storeIdempotentResponse(idempotencyKey, 202, body);
    return HttpResponse.json(body, { status: 202 });
  }),

  http.get("*/api/v1/documents", async ({ request }) => {
    const authError = requireAuth(request);
    if (authError) return authError;
    const scenario = await applyGlobalScenarios();
    if (scenario.shortCircuit) return scenario.shortCircuit;
    await plainReadDelay();

    const url = new URL(request.url);
    const cursor = url.searchParams.get("cursor");
    const limit = Number.parseInt(url.searchParams.get("limit") ?? "20", 10);
    return HttpResponse.json(paginate(db.listDocuments(), cursor, limit));
  }),

  http.get("*/api/v1/documents/:id", async ({ request, params }) => {
    const authError = requireAuth(request);
    if (authError) return authError;
    const scenario = await applyGlobalScenarios();
    if (scenario.shortCircuit) return scenario.shortCircuit;
    await plainReadDelay();

    const document = db.getDocument(params.id as string);
    if (!document || document.deleted_at) return notFound("No document with that id belongs to your household.");
    return HttpResponse.json(document);
  }),

  http.delete("*/api/v1/documents/:id", async ({ request, params }) => {
    const authError = requireAuth(request);
    if (authError) return authError;
    await plainReadDelay();

    const document = db.softDeleteDocument(params.id as string);
    if (!document) return notFound("No document with that id belongs to your household.");
    return new HttpResponse(null, { status: 204 });
  }),
];
