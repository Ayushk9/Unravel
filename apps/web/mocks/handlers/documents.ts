import { http, HttpResponse } from "msw";
import type { DocumentFile, DocumentType, DocumentTypeCorrectionRequest, JobAccepted, ParseDocumentResult, Policy } from "@/api/types";
import * as db from "../db";
import { policyById, retailPolicy } from "../fixtures";
import { errorResponse, genId, notFound, paginate, plainReadDelay, requireAuth } from "../utils";
import { applyGlobalScenarios } from "../scenarios";

const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
const ALLOWED_MIME_TYPES = ["application/pdf", "image/jpeg", "image/png", "image/heic", "image/webp"];

const DOCUMENT_TYPES: DocumentType[] = [
  "policy_schedule",
  "policy_wording",
  "discharge_summary",
  "itemised_bill",
  "payment_receipt",
  "investigation_report",
  "denial_letter",
  "id_proof",
  "unknown",
];

/**
 * Phase 4: the real extraction pipeline doesn't exist, but a claim wizard
 * demo where every uploaded document defaults to the same type would make
 * the "editable dropdown corrects a misclassification" feature untestable
 * except by accident. Keyword-matches the (user-chosen) file name as a
 * stand-in for real classification — mock-only, not a contract concern.
 */
function detectClaimDocumentType(fileName: string): DocumentType {
  const name = fileName.toLowerCase();
  if (name.includes("discharge")) return "discharge_summary";
  if (name.includes("bill") || name.includes("invoice")) return "itemised_bill";
  if (name.includes("receipt") || name.includes("payment")) return "payment_receipt";
  if (name.includes("aadhaar") || name.includes("pan") || name.includes("passport") || name.includes("id-proof") || name.includes("id_proof")) return "id_proof";
  if (name.includes("denial") || name.includes("repudiat")) return "denial_letter";
  if (name.includes("investigat") || name.includes("lab") || name.includes("report")) return "investigation_report";
  return "itemised_bill"; // reasonable default for a claim-context upload with no filename hint
}

/**
 * Runs once the parse_document job's simulated delay has elapsed. Registered
 * here (not passed as a closure to db.createJob) so the job record stays
 * plain, serializable data — required for it to survive a page refresh via
 * sessionStorage. Finalizes the document (parse_status -> parsed) and, for
 * policy-type uploads, creates the linked Policy — exactly once, since
 * db.getJob() only invokes this the first time a job is observed as elapsed
 * and caches the result from then on.
 */
db.registerJobResolver("parse_document", (params): ParseDocumentResult => {
  const { documentId, claimId } = params as { documentId: string; claimId: string | null };
  const looksLikePolicy = !claimId; // policy uploads happen outside a claim; claim uploads are bills/discharge summaries/etc.
  const detectedType: DocumentType = looksLikePolicy ? "policy_schedule" : detectClaimDocumentType(db.getDocument(documentId)?.file_name ?? "");

  db.updateDocument(documentId, {
    page_count: looksLikePolicy ? 4 : 2,
    detected_type: {
      value: detectedType,
      confidence: "high",
      provenance: { document_id: documentId, page: 1, bbox: null, snippet: null },
      user_confirmed: false,
    },
    parse_status: "parsed",
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
        // A fresh upload: nothing typed by the user yet (D-46).
        insurer_name: null,
        user_entered_fields: [],
        source_document_id: documentId,
      };
      if (newPolicy.coverage_profile) newPolicy.coverage_profile.policy_id = policyId;
      db.addPolicy(newPolicy);
    }
  }

  return { document_id: documentId, policy_id: policyId };
});

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

    // Created immediately, not after the job resolves — parse_status carries
    // the progress instead, so the upload screen can show file name and (an
    // estimated) page count throughout "Parsing", and GET /documents/{id}
    // works right away rather than 404ing until the job finishes.
    const documentId = genId("doc");
    db.addDocument({
      id: documentId,
      file_name: file.name,
      mime_type: file.type,
      page_count: claimId ? 2 : 4,
      uploaded_at: new Date().toISOString(),
      claim_id: claimId,
      detected_type: { value: null, confidence: "unknown", provenance: null, user_confirmed: false },
      parse_status: "queued",
      parse_error: null,
      deleted_at: null,
    });

    const job = db.createJob("parse_document", [4000, 8000], { documentId, claimId });

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
    // Phase 4: `claim_id` filters the same paginated collection rather than being a
    // new endpoint — the claim wizard's Documents step and the claim workspace's
    // Documents tab both need "this claim's documents only". See CONTRACTS.md §2/§4.
    const claimId = url.searchParams.get("claim_id");
    const source = claimId ? db.documentsForClaim(claimId) : db.listDocuments();
    return HttpResponse.json(paginate(source, cursor, limit));
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

  /**
   * D-26: a short-lived link to the document's file. The mock has no real
   * uploads, so every document resolves to the kitchen-sink fixture PDF —
   * the same file the viewer showed before this route existed.
   */
  http.get("*/api/v1/documents/:id/file", async ({ request, params }) => {
    const authError = requireAuth(request);
    if (authError) return authError;
    await plainReadDelay();

    const document = db.getDocument(params.id as string);
    if (!document || document.deleted_at) return notFound("No document with that id belongs to your household.");
    const body: DocumentFile = {
      url: "/kitchen-sink/sample-policy.pdf",
      expires_at: new Date(Date.now() + 5 * 60 * 1000).toISOString(),
    };
    return HttpResponse.json(body);
  }),

  /**
   * Phase 4 addition, not in the ratified endpoint list (see DECISIONS.md and
   * CONTRACTS.md §4): corrects a misclassified `detected_type`. Modelled on
   * D-15's PATCH-a-field pattern rather than a whole-resource PUT — it's a
   * single targeted correction, and it marks the correction as confirmed the
   * same way a coverage-profile field correction does.
   */
  http.patch("*/api/v1/documents/:id", async ({ request, params }) => {
    const authError = requireAuth(request);
    if (authError) return authError;
    await plainReadDelay();

    const document = db.getDocument(params.id as string);
    if (!document || document.deleted_at) return notFound("No document with that id belongs to your household.");

    const body = (await request.json()) as DocumentTypeCorrectionRequest;
    if (!DOCUMENT_TYPES.includes(body.detected_type)) {
      return errorResponse(422, {
        code: "validation_error",
        message: "Not a recognised document type.",
        field_errors: [{ field: "detected_type", message: "Unknown document type." }],
      });
    }

    const updated = db.updateDocument(document.id, {
      detected_type: { ...document.detected_type, value: body.detected_type, confidence: "high", user_confirmed: true },
    });
    return HttpResponse.json(updated);
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
