import type { StoredDocument } from "@/api/types";
import { ids } from "./ids";

function parsed(doc: Omit<StoredDocument, "parse_status" | "parse_error" | "deleted_at">): StoredDocument {
  return { ...doc, parse_status: "parsed", parse_error: null, deleted_at: null };
}

export const documents: StoredDocument[] = [
  parsed({
    id: ids.document.groupSchedule,
    file_name: "kavach-corporate-health-shield-schedule.pdf",
    mime_type: "application/pdf",
    page_count: 6,
    uploaded_at: "2026-04-03T09:12:00+05:30",
    claim_id: null,
    detected_type: {
      value: "policy_schedule",
      confidence: "high",
      provenance: { document_id: ids.document.groupSchedule, page: 1, bbox: null, snippet: "Policy Schedule" },
      user_confirmed: true,
    },
  }),
  parsed({
    id: ids.document.retailSchedule,
    file_name: "suraksha-complete-health-plan-schedule.pdf",
    mime_type: "application/pdf",
    page_count: 4,
    uploaded_at: "2023-04-02T18:45:00+05:30",
    claim_id: null,
    detected_type: {
      value: "policy_schedule",
      confidence: "high",
      provenance: { document_id: ids.document.retailSchedule, page: 1, bbox: null, snippet: "Policy Schedule" },
      user_confirmed: true,
    },
  }),
  parsed({
    id: ids.document.retailWording,
    file_name: "suraksha-complete-health-plan-wording.pdf",
    mime_type: "application/pdf",
    page_count: 42,
    uploaded_at: "2023-04-02T18:47:00+05:30",
    claim_id: null,
    detected_type: {
      value: "policy_wording",
      confidence: "medium",
      provenance: { document_id: ids.document.retailWording, page: 1, bbox: null, snippet: "Terms and Conditions" },
      user_confirmed: false,
    },
  }),
  parsed({
    id: ids.document.deniedDischarge,
    file_name: "discharge-summary-jul-2026.pdf",
    mime_type: "application/pdf",
    page_count: 3,
    uploaded_at: "2026-07-12T14:05:00+05:30",
    claim_id: ids.claim.denied,
    detected_type: {
      value: "discharge_summary",
      confidence: "high",
      provenance: { document_id: ids.document.deniedDischarge, page: 1, bbox: null, snippet: "Discharge Summary" },
      user_confirmed: true,
    },
  }),
  parsed({
    id: ids.document.deniedBill,
    file_name: "hospital-bill-jul-2026.pdf",
    mime_type: "application/pdf",
    page_count: 2,
    uploaded_at: "2026-07-12T14:08:00+05:30",
    claim_id: ids.claim.denied,
    detected_type: {
      value: "itemised_bill",
      confidence: "high",
      provenance: { document_id: ids.document.deniedBill, page: 1, bbox: null, snippet: "Itemised Bill" },
      user_confirmed: true,
    },
  }),
  parsed({
    id: ids.document.deniedDenialLetter,
    file_name: "denial-letter-suraksha-aug-2026.pdf",
    mime_type: "application/pdf",
    page_count: 1,
    uploaded_at: "2026-08-10T16:20:00+05:30",
    claim_id: ids.claim.denied,
    detected_type: {
      value: "denial_letter",
      confidence: "high",
      provenance: { document_id: ids.document.deniedDenialLetter, page: 1, bbox: null, snippet: "Claim Denial Letter" },
      user_confirmed: true,
    },
  }),
  parsed({
    id: ids.document.underReviewDischarge,
    file_name: "discharge-summary-aug-2026.pdf",
    mime_type: "application/pdf",
    page_count: 2,
    uploaded_at: "2026-08-15T11:30:00+05:30",
    claim_id: ids.claim.underReview,
    detected_type: {
      value: "discharge_summary",
      confidence: "high",
      provenance: { document_id: ids.document.underReviewDischarge, page: 1, bbox: null, snippet: "Discharge Summary" },
      user_confirmed: true,
    },
  }),
  parsed({
    id: ids.document.underReviewIdProof,
    file_name: "aadhaar-card.pdf",
    mime_type: "application/pdf",
    page_count: 1,
    uploaded_at: "2026-08-16T10:02:00+05:30",
    claim_id: ids.claim.underReview,
    detected_type: {
      value: "id_proof",
      confidence: "high",
      provenance: { document_id: ids.document.underReviewIdProof, page: 1, bbox: null, snippet: "Aadhaar" },
      user_confirmed: true,
    },
  }),
  parsed({
    id: ids.document.underReviewReceipt,
    file_name: "payment-receipt-aug-2026.pdf",
    mime_type: "application/pdf",
    page_count: 1,
    uploaded_at: "2026-08-16T10:05:00+05:30",
    claim_id: ids.claim.underReview,
    detected_type: {
      value: "payment_receipt",
      confidence: "high",
      provenance: { document_id: ids.document.underReviewReceipt, page: 1, bbox: null, snippet: "Payment Receipt" },
      user_confirmed: true,
    },
  }),
  parsed({
    id: ids.document.settledDischarge,
    file_name: "discharge-summary-feb-2026.pdf",
    mime_type: "application/pdf",
    page_count: 2,
    uploaded_at: "2026-02-10T10:00:00+05:30",
    claim_id: ids.claim.settled,
    detected_type: {
      value: "discharge_summary",
      confidence: "high",
      provenance: { document_id: ids.document.settledDischarge, page: 1, bbox: null, snippet: "Discharge Summary" },
      user_confirmed: true,
    },
  }),
  parsed({
    id: ids.document.settledBill,
    file_name: "hospital-bill-feb-2026.pdf",
    mime_type: "application/pdf",
    page_count: 1,
    uploaded_at: "2026-02-10T10:05:00+05:30",
    claim_id: ids.claim.settled,
    detected_type: {
      value: "itemised_bill",
      confidence: "high",
      provenance: { document_id: ids.document.settledBill, page: 1, bbox: null, snippet: "Itemised Bill" },
      user_confirmed: true,
    },
  }),
];

export function documentById(id: string): StoredDocument | undefined {
  return documents.find((d) => d.id === id);
}
