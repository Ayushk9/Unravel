/**
 * Hand-written domain contract, authoritative until the backend ships its first
 * FastAPI route (docs/API_DECISIONS.md D-21). Once openapi-typescript generation
 * is wired up, this file is deleted, not kept in parallel with the generated one.
 *
 * Conventions: money is integer paise (never floats), dates are ISO-8601 strings,
 * ids are UUID strings, field names are snake_case to match the backend wire
 * format exactly (D-02) — never camelCased at this boundary. Every field is
 * present in every response; unknown values are `null`, never omitted (D-05).
 *
 * D-06: every string enum carries an explicit escape-hatch member so an added
 * backend value degrades to a neutral rendering instead of a crash. Phase 0/1
 * copied the brief's enums verbatim and missed several — this file is the
 * corrected version; see /DECISIONS.md "Phase 2" for the "unknown" vs "other"
 * convention used below and which enums intentionally did NOT get one.
 */

export type UUID = string;
export type ISODate = string; // "2026-03-01"
export type ISODateTime = string; // "2026-03-01T09:15:00+05:30"
export type Paise = number; // ₹5,000 => 500000

export type Confidence = "high" | "medium" | "low" | "unknown";

export interface Provenance {
  document_id: UUID;
  page: number; // 1-indexed
  bbox: [number, number, number, number] | null; // x0,y0,x1,y1 normalised 0..1, top-left origin
  snippet: string | null;
}

export interface Extracted<T> {
  value: T | null;
  confidence: Confidence;
  provenance: Provenance | null;
  user_confirmed: boolean;
}

// --- Engine A / D: policy ---
export interface Insurer {
  id: UUID;
  name: string;
  irdai_code: string | null;
}

export interface SubLimit {
  category: "room_rent" | "icu" | "procedure" | "ambulance" | "opd" | "other";
  label: string;
  cap_amount: Extracted<Paise>;
  cap_basis: "per_day" | "per_claim" | "per_policy_year" | "percent_of_sum_insured" | "other";
  percent_value: number | null;
}

export interface WaitingPeriod {
  kind: "initial" | "disease_specific" | "pre_existing" | "maternity" | "other";
  months: Extracted<number>;
  applies_to: string | null; // e.g. "cataract"
  starts_on: ISODate | null;
  expires_on: ISODate | null; // derived server-side
}

export interface CoverageProfile {
  policy_id: UUID;
  sum_insured: Extracted<Paise>;
  co_pay_percent: Extracted<number>;
  sub_limits: SubLimit[];
  waiting_periods: WaitingPeriod[];
  exclusions: Extracted<string>[];
  intimation_deadline_hours: Extracted<number>;
  extraction_completeness: number; // 0..1, drives the "review these fields" banner
}

// D-40: the household's own choice of what kind of city it lives in. "other" is the escape hatch.
export type CityTier = "metro" | "tier_2" | "other";

export interface Household {
  id: UUID;
  name: string;
  city_tier: CityTier | null; // null until the household chooses
}

export interface Member {
  id: UUID;
  full_name: string;
  relationship: string;
  date_of_birth: ISODate | null;
}

export interface Policy {
  id: UUID;
  // API_DECISIONS D-25: these five are null when the uploaded document did
  // not state them (a policy wording PDF often has no policy number or
  // dates). Render a null as "not stated", never as a placeholder value.
  insurer: Insurer | null;
  policy_number: string | null;
  product_name: string | null;
  policy_type: "individual" | "family_floater" | "group_employer" | "top_up" | "other";
  start_date: ISODate | null;
  end_date: ISODate | null;
  // D-39: the start of cover renewed without a break, entered by the user.
  // Waiting periods count from it when set, otherwise from start_date.
  first_inception_date: ISODate | null;
  members: Member[];
  coverage_profile: CoverageProfile | null; // null while parsing
  source_document_id: UUID;
}

// --- Engine A: documents ---
export type DocumentType =
  | "policy_schedule"
  | "policy_wording"
  | "discharge_summary"
  | "itemised_bill"
  | "payment_receipt"
  | "investigation_report"
  | "denial_letter"
  | "id_proof"
  | "unknown";

export interface StoredDocument {
  id: UUID;
  file_name: string;
  mime_type: string;
  page_count: number;
  uploaded_at: ISODateTime;
  detected_type: Extracted<DocumentType>;
  parse_status: "queued" | "parsing" | "parsed" | "failed" | "unknown";
  parse_error: string | null;
  deleted_at: ISODateTime | null; // D-20: documents are soft-deleted
  // Not in the brief's original type — added in Phase 2. Without it there is
  // no way to know which documents belong to a claim, which Feature 4
  // (completeness) and the claim workspace's Documents tab both need. See
  // DECISIONS.md. Null for documents uploaded outside a claim (e.g. a policy
  // schedule).
  claim_id: UUID | null;
}

// API_DECISIONS D-26: GET /documents/{id}/file. `url` is a short-lived link
// to the stored file that needs no Authorization header.
export interface DocumentFile {
  url: string;
  expires_at: ISODateTime;
}

// --- Engine B: eligibility ---
export type CheckStatus = "satisfied" | "at_risk" | "failed" | "unknown";

// D-36: a fact a check needs and doesn't have, and where to get it.
export interface MissingFact {
  fact: string;
  where_to_get: string;
  // A document type that would provide it; null when no document does (e.g. "is it pre-existing?").
  resolving_document: DocumentType | null;
}

// D-36: what a check's sentence was rendered from. Dates are "YYYY-MM-DD",
// month/day counts and paise are integers. Keys are rule-specific.
export type CheckValue = string | number | boolean | null;

export interface EligibilityCheck {
  id: string; // stable rule id, e.g. "ped_waiting_period"
  title: string; // "Pre-existing disease waiting period"
  status: CheckStatus;
  explanation: string; // plain language, includes date arithmetic
  governing_clause: Provenance | null;
  missing_fact: string | null; // the first of missing_facts, for older clients
  resolving_document: DocumentType | null; // ditto
  // D-36: the lowest confidence among the check's inputs. A three-level label, never a probability.
  confidence: Confidence;
  values: Record<string, CheckValue>;
  missing_facts: MissingFact[];
}

export interface EligibilityAssessment {
  claim_id: UUID;
  // NOT given a separate "unknown" escape hatch: insufficient_information already
  // is this enum's "we don't know" state. A second, near-synonymous value would
  // confuse rather than protect — see DECISIONS.md.
  band: "likely_eligible" | "at_risk" | "likely_ineligible" | "insufficient_information";
  checks: EligibilityCheck[];
  ombudsman_precedent: OmbudsmanAward[]; // similar fact patterns, may be empty
  // D-36: why ombudsman_precedent is empty, e.g. "Precedent corpus not yet loaded ...".
  ombudsman_precedent_note: string | null;
  generated_at: ISODateTime;
}

// --- Engine B: bill validation ---
export interface BillLineItem {
  id: UUID;
  description: string;
  quantity: number;
  rate: Paise;
  amount: Paise;
  provenance: Provenance | null;
}

export interface ValidationFlag {
  severity: "info" | "warning" | "error" | "unknown";
  rule: "non_payable_item" | "duplicate_line" | "arithmetic_mismatch" | "sub_limit_breach" | "other";
  message: string;
  line_item_ids: UUID[];
  estimated_impact: Paise | null;
}

export interface BillValidationReport {
  claim_id: UUID;
  line_items: BillLineItem[];
  flags: ValidationFlag[];
  total_billed: Paise;
  total_at_risk: Paise;
  generated_at: ISODateTime;
}

// --- Engine B: document completeness ---
export interface CompletenessReport {
  claim_id: UUID;
  required: DocumentType[];
  present: DocumentType[];
  missing: DocumentType[];
  advisory_note: string;
  // D-35: one entry per required type, in the same order as `required`.
  required_details: RequiredDocumentDetail[];
  // D-35: false until the checklist has been checked against an official source.
  verified: boolean;
}

export interface RequiredDocumentDetail {
  type: DocumentType;
  description: string;
  where_to_get: string;
  source: RuleSource;
}

// --- Engine D: claim lifecycle ---
// "unknown" here is a defensive parse-time fallback only — never a value the
// client sets, and never a legal transition target in the state machine.
export type ClaimState =
  | "intimated"
  | "documents_submitted"
  | "under_review"
  | "queried"
  | "approved"
  | "denied"
  | "escalated"
  | "resolved"
  | "unknown";

export interface ClaimEvent {
  id: UUID;
  claim_id: UUID;
  from_state: ClaimState | null;
  to_state: ClaimState;
  occurred_at: ISODateTime;
  note: string | null;
  source: "user" | "insurer_letter" | "system" | "unknown";
}

// Where a rule comes from, so it can be checked (API_DECISIONS D-33).
export interface RuleSource {
  document: string;
  section: string | null;
  url: string | null;
}

export interface Deadline {
  id: string;
  label: string; // "Ombudsman filing window"
  due_at: ISODateTime;
  days_remaining: number;
  basis: string; // the rule in plain language, with the date it was counted from
  urgency: "normal" | "soon" | "critical" | "expired" | "unknown";
  source: RuleSource | null;
  // D-33: false until a person has checked the rule against its source.
  // An unverified deadline must be shown as unverified, never as settled fact.
  verified: boolean;
}

// D-33: a deadline that could not be worked out, and why. Never guessed instead.
export interface OmittedDeadline {
  id: string;
  label: string;
  reason: string;
}

export interface Claim {
  id: UUID;
  policy_id: UUID;
  member_id: UUID;
  claim_type: "cashless" | "reimbursement" | "other";
  admission_type: "planned" | "emergency" | "other";
  hospital_name: string;
  admitted_on: ISODate | null;
  discharged_on: ISODate | null;
  claimed_amount: Paise | null;
  settled_amount: Paise | null;
  current_state: ClaimState; // projection over the event log
  events: ClaimEvent[];
  deadlines: Deadline[];
  omitted_deadlines: OmittedDeadline[];
  facts: ClaimFacts; // D-37
}

// D-37: what the user has told us about the illness and the stay. null means
// "not answered" (the rule that needs it says unknown); [] means "none apply".
export interface ClaimFacts {
  diagnosis: string | null; // display only; no rule reads it
  condition_is_pre_existing: boolean | null;
  first_diagnosed_on: ISODate | null;
  matched_waiting_periods: number[] | null; // positions in coverage_profile.waiting_periods (disease_specific only)
  matched_exclusions: number[] | null; // positions in coverage_profile.exclusions
  planned_room_rent_per_day: Paise | null;
}

// --- Engine C: grounded generation ---
export interface Citation {
  id: string;
  kind: "policy_clause" | "regulation" | "ombudsman_award" | "other";
  label: string;
  provenance: Provenance | null;
  external_url: string | null;
}

export interface GrievanceDraft {
  id: UUID;
  claim_id: UUID;
  rung: "insurer_grievance_cell" | "irdai_bima_bharosa" | "insurance_ombudsman" | "other";
  subject: string;
  paragraphs: { text: string; citation_ids: string[]; verified: boolean }[];
  citations: Citation[];
  evidence_checklist: { item: string; satisfied: boolean }[];
  citation_precision: number; // 0..1, shown in the QA strip
}

export interface OmbudsmanAward {
  id: UUID;
  case_reference: string;
  insurer_name: string;
  decided_on: ISODate;
  denial_ground: string;
  outcome: "upheld" | "overturned" | "partially_allowed" | "unknown";
  summary: string;
  external_url: string | null;
}

// --- Engine B: alerts ---
export interface Alert {
  id: string; // D-38: deterministic, e.g. "alert-low_sum_insured-<policy_id>", not a UUID
  policy_id: UUID;
  kind:
    | "room_rent_below_market"
    | "waiting_period_expiring"
    | "renewal_due"
    | "no_maternity_cover"
    | "low_sum_insured"
    | "other";
  severity: "info" | "warning" | "critical" | "unknown";
  title: string;
  explanation: string;
  suggested_action: string | null;
  reference_source: string | null; // for estimate-based alerts
  triggers_on: ISODate | null;
  // D-38: false when the alert rests on a reference figure nobody has checked. Show it as an estimate.
  verified: boolean;
  // D-38: the policy field the alert is based on; null when it is about something not being found.
  provenance: Provenance | null;
}

// --- Engine D: benchmarking ---
export interface InsurerBenchmark {
  insurer: Insurer;
  period: string; // "FY2024-25"
  claim_settlement_ratio: number | null;
  incurred_claims_ratio: number | null;
  avg_turnaround_days: number | null; // often null — render "Not reported"
  complaints_per_10k_policies: number | null;
  ombudsman_cases_lost_share: number | null;
  source: { name: string; published_on: ISODate; url: string };
}

// --- Transport envelope (docs/API_DECISIONS.md D-03) ---
export interface Collection<T> {
  items: T[];
  next_cursor: string | null;
  total: number | null;
}

export interface ApiFieldError {
  field: string;
  message: string;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    field_errors: ApiFieldError[];
    request_id: string;
    retryable: boolean;
  };
}

// --- Long-running jobs (D-07) ---
export type JobKind = "parse_document" | "answer_question" | "generate_grievance_draft";
export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "unknown";

export interface JobAccepted {
  job_id: UUID;
  kind: JobKind;
  status: "queued";
}

export interface Job<TResult = unknown> {
  job_id: UUID;
  kind: JobKind;
  status: JobStatus;
  progress: { step: string; percent: number } | null;
  result: TResult | null;
  error: string | null;
}

export interface ParseDocumentResult {
  document_id: UUID;
  // Only policy_schedule/policy_wording uploads produce a Policy. Everything
  // else (bills, discharge summaries, ...) just gets classified and parsed
  // into whatever line items its type calls for.
  policy_id: UUID | null;
}

export interface QuestionAnswerResult {
  answer: string;
  citations: Citation[];
  abstained: boolean;
  missing_context: string | null;
}

// --- Request bodies ---
export interface DocumentUploadMeta {
  // Sent as multipart form fields alongside the file (D-18), not JSON.
  claim_id: UUID | null; // set when uploading in the claim wizard, else null
}

export interface PolicyCreateRequest {
  source_document_id: UUID;
}

// D-39: only the keys sent change; a key sent as null clears that date.
export interface PolicyDatesUpdateRequest {
  start_date?: ISODate | null;
  end_date?: ISODate | null;
  first_inception_date?: ISODate | null;
}

// D-40
export interface HouseholdUpdateRequest {
  city_tier: CityTier | null;
}

// D-37: PUT /claims/{id}/facts is a full replacement.
export type ClaimFactsRequest = ClaimFacts;

/**
 * D-15 / D-41: field_path is one of sum_insured, co_pay_percent,
 * intimation_deadline_hours, sub_limits.<position>.cap_amount,
 * waiting_periods.<position>.months. <position> is the 0-based index in the
 * list as GET /policies/{id} returns it. The older sub_limits.<category>.cap_amount
 * form still works but is a 409 when two rows share the category.
 */
export interface FieldCorrectionRequest {
  value: string | number | boolean | null;
  user_confirmed: boolean;
}

export interface ClaimCreateRequest {
  policy_id: UUID;
  member_id: UUID;
  claim_type: Claim["claim_type"];
  admission_type: Claim["admission_type"];
  hospital_name: string;
  admitted_on: ISODate | null;
  discharged_on: ISODate | null;
  claimed_amount: Paise | null;
}

export interface ClaimEventRequest {
  to_state: ClaimState;
  occurred_at: ISODateTime;
  note: string | null;
}

export interface QuestionRequest {
  question: string;
}

// Phase 4 addition — not in the ratified D-15-style list, but the claim
// wizard's Documents step and the claim workspace's Documents tab both need
// a way to correct an auto-detected document type. See DECISIONS.md.
export interface DocumentTypeCorrectionRequest {
  detected_type: DocumentType;
}

export interface GrievanceDraftRequest {
  rung: GrievanceDraft["rung"];
}
