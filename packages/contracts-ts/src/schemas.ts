/**
 * zod schemas mirroring every response body in types.ts, used to parse at the
 * client boundary (src/api/client.ts). Every enum parses through `.catch(...)`
 * (D-06) so a backend value the frontend doesn't recognise yet degrades to the
 * escape-hatch member instead of throwing — see types.ts for which member each
 * enum uses and why.
 */
import { z } from "zod";

export const uuidSchema = z.string();
export const isoDateSchema = z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "expected YYYY-MM-DD");
export const isoDateTimeSchema = z
  .string()
  .regex(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$/, "expected ISO-8601 with offset");

export const confidenceSchema = z.enum(["high", "medium", "low", "unknown"]).catch("unknown");

export const provenanceSchema = z.object({
  document_id: uuidSchema,
  page: z.number().int().positive(),
  bbox: z.tuple([z.number(), z.number(), z.number(), z.number()]).nullable(),
  snippet: z.string().nullable(),
});

function extractedSchema<T extends z.ZodType>(valueSchema: T) {
  return z.object({
    value: valueSchema.nullable(),
    confidence: confidenceSchema,
    provenance: provenanceSchema.nullable(),
    user_confirmed: z.boolean(),
  });
}

export const insurerSchema = z.object({
  id: uuidSchema,
  name: z.string(),
  irdai_code: z.string().nullable(),
});

export const subLimitSchema = z.object({
  category: z.enum(["room_rent", "icu", "procedure", "ambulance", "opd", "other"]).catch("other"),
  label: z.string(),
  cap_amount: extractedSchema(z.number()),
  cap_basis: z
    .enum(["per_day", "per_claim", "per_policy_year", "percent_of_sum_insured", "other"])
    .catch("other"),
  percent_value: z.number().nullable(),
});

export const waitingPeriodSchema = z.object({
  kind: z.enum(["initial", "disease_specific", "pre_existing", "maternity", "other"]).catch("other"),
  months: extractedSchema(z.number()),
  applies_to: z.string().nullable(),
  starts_on: isoDateSchema.nullable(),
  expires_on: isoDateSchema.nullable(),
});

export const coverageProfileSchema = z.object({
  policy_id: uuidSchema,
  sum_insured: extractedSchema(z.number()),
  co_pay_percent: extractedSchema(z.number()),
  sub_limits: z.array(subLimitSchema),
  waiting_periods: z.array(waitingPeriodSchema),
  exclusions: z.array(extractedSchema(z.string())),
  intimation_deadline_hours: extractedSchema(z.number()),
  extraction_completeness: z.number().min(0).max(1),
});

export const memberSchema = z.object({
  id: uuidSchema,
  full_name: z.string(),
  relationship: z.string(),
  date_of_birth: isoDateSchema.nullable(),
});

export const policySchema = z.object({
  id: uuidSchema,
  insurer: insurerSchema,
  policy_number: z.string(),
  product_name: z.string(),
  policy_type: z.enum(["individual", "family_floater", "group_employer", "top_up", "other"]).catch("other"),
  start_date: isoDateSchema,
  end_date: isoDateSchema,
  members: z.array(memberSchema),
  coverage_profile: coverageProfileSchema.nullable(),
  source_document_id: uuidSchema,
});

export const documentTypeSchema = z
  .enum([
    "policy_schedule",
    "policy_wording",
    "discharge_summary",
    "itemised_bill",
    "payment_receipt",
    "investigation_report",
    "denial_letter",
    "id_proof",
    "unknown",
  ])
  .catch("unknown");

export const storedDocumentSchema = z.object({
  id: uuidSchema,
  file_name: z.string(),
  mime_type: z.string(),
  page_count: z.number().int().nonnegative(),
  uploaded_at: isoDateTimeSchema,
  detected_type: extractedSchema(documentTypeSchema),
  parse_status: z.enum(["queued", "parsing", "parsed", "failed", "unknown"]).catch("unknown"),
  parse_error: z.string().nullable(),
  deleted_at: isoDateTimeSchema.nullable(),
  claim_id: uuidSchema.nullable(),
});

export const checkStatusSchema = z.enum(["satisfied", "at_risk", "failed", "unknown"]).catch("unknown");

export const eligibilityCheckSchema = z.object({
  id: z.string(),
  title: z.string(),
  status: checkStatusSchema,
  explanation: z.string(),
  governing_clause: provenanceSchema.nullable(),
  missing_fact: z.string().nullable(),
  resolving_document: documentTypeSchema.nullable(),
});

// Forward-declared below (ombudsmanAwardSchema) — eligibility assessments embed awards.
export const eligibilityAssessmentSchema = z.object({
  claim_id: uuidSchema,
  band: z.enum(["likely_eligible", "at_risk", "likely_ineligible", "insufficient_information"]),
  checks: z.array(eligibilityCheckSchema),
  ombudsman_precedent: z.array(z.lazy(() => ombudsmanAwardSchema)),
  generated_at: isoDateTimeSchema,
});

export const billLineItemSchema = z.object({
  id: uuidSchema,
  description: z.string(),
  quantity: z.number(),
  rate: z.number(),
  amount: z.number(),
  provenance: provenanceSchema.nullable(),
});

export const validationFlagSchema = z.object({
  severity: z.enum(["info", "warning", "error", "unknown"]).catch("unknown"),
  rule: z
    .enum(["non_payable_item", "duplicate_line", "arithmetic_mismatch", "sub_limit_breach", "other"])
    .catch("other"),
  message: z.string(),
  line_item_ids: z.array(uuidSchema),
  estimated_impact: z.number().nullable(),
});

export const billValidationReportSchema = z.object({
  claim_id: uuidSchema,
  line_items: z.array(billLineItemSchema),
  flags: z.array(validationFlagSchema),
  total_billed: z.number(),
  total_at_risk: z.number(),
  generated_at: isoDateTimeSchema,
});

export const completenessReportSchema = z.object({
  claim_id: uuidSchema,
  required: z.array(documentTypeSchema),
  present: z.array(documentTypeSchema),
  missing: z.array(documentTypeSchema),
  advisory_note: z.string(),
});

export const claimStateSchema = z
  .enum([
    "intimated",
    "documents_submitted",
    "under_review",
    "queried",
    "approved",
    "denied",
    "escalated",
    "resolved",
    "unknown",
  ])
  .catch("unknown");

export const claimEventSchema = z.object({
  id: uuidSchema,
  claim_id: uuidSchema,
  from_state: claimStateSchema.nullable(),
  to_state: claimStateSchema,
  occurred_at: isoDateTimeSchema,
  note: z.string().nullable(),
  source: z.enum(["user", "insurer_letter", "system", "unknown"]).catch("unknown"),
});

export const deadlineSchema = z.object({
  id: z.string(),
  label: z.string(),
  due_at: isoDateTimeSchema,
  days_remaining: z.number().int(),
  basis: z.string(),
  urgency: z.enum(["normal", "soon", "critical", "expired", "unknown"]).catch("unknown"),
});

export const claimSchema = z.object({
  id: uuidSchema,
  policy_id: uuidSchema,
  member_id: uuidSchema,
  claim_type: z.enum(["cashless", "reimbursement", "other"]).catch("other"),
  admission_type: z.enum(["planned", "emergency", "other"]).catch("other"),
  hospital_name: z.string(),
  admitted_on: isoDateSchema.nullable(),
  discharged_on: isoDateSchema.nullable(),
  claimed_amount: z.number().nullable(),
  settled_amount: z.number().nullable(),
  current_state: claimStateSchema,
  events: z.array(claimEventSchema),
  deadlines: z.array(deadlineSchema),
});

export const citationSchema = z.object({
  id: z.string(),
  kind: z.enum(["policy_clause", "regulation", "ombudsman_award", "other"]).catch("other"),
  label: z.string(),
  provenance: provenanceSchema.nullable(),
  external_url: z.string().nullable(),
});

export const grievanceDraftSchema = z.object({
  id: uuidSchema,
  claim_id: uuidSchema,
  rung: z
    .enum(["insurer_grievance_cell", "irdai_bima_bharosa", "insurance_ombudsman", "other"])
    .catch("other"),
  subject: z.string(),
  paragraphs: z.array(
    z.object({
      text: z.string(),
      citation_ids: z.array(z.string()),
      verified: z.boolean(),
    }),
  ),
  citations: z.array(citationSchema),
  evidence_checklist: z.array(z.object({ item: z.string(), satisfied: z.boolean() })),
  citation_precision: z.number().min(0).max(1),
});

export const ombudsmanAwardSchema = z.object({
  id: uuidSchema,
  case_reference: z.string(),
  insurer_name: z.string(),
  decided_on: isoDateSchema,
  denial_ground: z.string(),
  outcome: z.enum(["upheld", "overturned", "partially_allowed", "unknown"]).catch("unknown"),
  summary: z.string(),
  external_url: z.string().nullable(),
});

export const alertSchema = z.object({
  id: uuidSchema,
  policy_id: uuidSchema,
  kind: z
    .enum([
      "room_rent_below_market",
      "waiting_period_expiring",
      "renewal_due",
      "no_maternity_cover",
      "low_sum_insured",
      "other",
    ])
    .catch("other"),
  severity: z.enum(["info", "warning", "critical", "unknown"]).catch("unknown"),
  title: z.string(),
  explanation: z.string(),
  suggested_action: z.string().nullable(),
  reference_source: z.string().nullable(),
  triggers_on: isoDateSchema.nullable(),
});

export const insurerBenchmarkSchema = z.object({
  insurer: insurerSchema,
  period: z.string(),
  claim_settlement_ratio: z.number().nullable(),
  incurred_claims_ratio: z.number().nullable(),
  avg_turnaround_days: z.number().nullable(),
  complaints_per_10k_policies: z.number().nullable(),
  ombudsman_cases_lost_share: z.number().nullable(),
  source: z.object({ name: z.string(), published_on: isoDateSchema, url: z.string() }),
});

export function collectionSchema<T extends z.ZodType>(itemSchema: T) {
  return z.object({
    items: z.array(itemSchema),
    next_cursor: z.string().nullable(),
    total: z.number().nullable(),
  });
}

export const apiFieldErrorSchema = z.object({
  field: z.string(),
  message: z.string(),
});

export const apiErrorBodySchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    field_errors: z.array(apiFieldErrorSchema),
    request_id: z.string(),
    retryable: z.boolean(),
  }),
});

export const jobStatusSchema = z.enum(["queued", "running", "succeeded", "failed", "unknown"]).catch("unknown");

export function jobSchema<T extends z.ZodType>(resultSchema: T) {
  return z.object({
    job_id: uuidSchema,
    kind: z.enum(["parse_document", "answer_question", "generate_grievance_draft"]),
    status: jobStatusSchema,
    progress: z.object({ step: z.string(), percent: z.number() }).nullable(),
    result: resultSchema.nullable(),
    error: z.string().nullable(),
  });
}

export const jobAcceptedSchema = z.object({
  job_id: uuidSchema,
  kind: z.enum(["parse_document", "answer_question", "generate_grievance_draft"]),
  status: z.literal("queued"),
});

export const parseDocumentResultSchema = z.object({
  document_id: uuidSchema,
  policy_id: uuidSchema.nullable(),
});

export const questionAnswerResultSchema = z.object({
  answer: z.string(),
  citations: z.array(citationSchema),
  abstained: z.boolean(),
  missing_context: z.string().nullable(),
});
