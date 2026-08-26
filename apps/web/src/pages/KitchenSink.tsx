import { useState, type ReactNode } from "react";
import type { Alert, Citation, Deadline, Policy, Provenance, SubLimit, WaitingPeriod } from "@/api/types";
import {
  AbstentionCard,
  AlertCard,
  CitationList,
  CitedProse,
  ConfidenceBadge,
  DeadlineCard,
  DocumentViewer,
  EmptyState,
  ErrorState,
  ExtractedField,
  FileDropzone,
  JobProgress,
  Money,
  PolicyCard,
  ProvenanceChip,
  Skeleton,
  SubLimitsTable,
  VerdictBand,
  WaitingPeriodTimeline,
} from "@/components/primitives";

const SAMPLE_PDF = "/kitchen-sink/sample-policy.pdf";

const roomRentProvenance: Provenance = {
  document_id: "doc-sample-policy",
  page: 1,
  bbox: [0.1111, 0.1641, 0.7026, 0.1869],
  snippet: "Room rent is limited to a maximum of Rs 5,000 per day.",
};

const pedWaitingProvenance: Provenance = {
  document_id: "doc-sample-policy",
  page: 1,
  bbox: [0.1111, 0.2689, 0.8497, 0.2841],
  snippet: "Pre-existing diseases are covered after 48 months of continuous cover.",
};

const exclusionProvenanceNoBbox: Provenance = {
  document_id: "doc-sample-policy",
  page: 2,
  bbox: null,
  snippet: "Cosmetic surgery is excluded unless medically necessitated by an accident covered under this policy.",
};

const sampleDeadlines: Deadline[] = [
  {
    id: "d-normal",
    label: "Policy renewal",
    due_at: "2027-03-14T00:00:00+05:30",
    days_remaining: 204,
    basis: "Policy end date, 14 Mar 2024 + 3 years",
    urgency: "normal",
  },
  {
    id: "d-soon",
    label: "Pre-existing waiting period expires",
    due_at: "2026-09-02T00:00:00+05:30",
    days_remaining: 11,
    basis: "48-month PED waiting period from policy start, 2 Sep 2022",
    urgency: "soon",
  },
  {
    id: "d-critical",
    label: "Ombudsman filing window",
    due_at: "2026-08-27T00:00:00+05:30",
    days_remaining: 5,
    basis: "Filing window from date of repudiation, 28 Jun 2026 — see DECISIONS.md, unverified figure",
    urgency: "critical",
  },
  {
    id: "d-expired",
    label: "Cashless pre-authorisation window",
    due_at: "2026-04-02T00:00:00+05:30",
    days_remaining: -140,
    basis: "48 hours from planned admission, 31 Mar 2026",
    urgency: "expired",
  },
];

const sampleCitations: Citation[] = [
  {
    id: "c-1",
    kind: "policy_clause",
    label: "Clause 4.2 — Room rent sub-limit",
    provenance: roomRentProvenance,
    external_url: null,
  },
  {
    id: "c-2",
    kind: "regulation",
    label: "IRDAI (Health Insurance) Regulations, 2016",
    provenance: null,
    external_url: "https://irdai.gov.in",
  },
  {
    id: "c-3",
    kind: "ombudsman_award",
    label: "Case Ref. GIC/2024/0142 — PED denial overturned",
    provenance: null,
    external_url: "https://cioins.co.in",
  },
];

const sampleSubLimits: SubLimit[] = [
  {
    category: "room_rent",
    label: "Room rent",
    cap_amount: { value: 500000, confidence: "low", provenance: roomRentProvenance, user_confirmed: false },
    cap_basis: "per_day",
    percent_value: null,
  },
  {
    category: "icu",
    label: "ICU",
    cap_amount: { value: 1000000, confidence: "high", provenance: roomRentProvenance, user_confirmed: true },
    cap_basis: "per_day",
    percent_value: null,
  },
];

const sampleWaitingPeriodActive: WaitingPeriod = {
  kind: "pre_existing",
  months: { value: 48, confidence: "high", provenance: pedWaitingProvenance, user_confirmed: true },
  applies_to: null,
  starts_on: "2023-01-01",
  expires_on: "2027-01-01",
};

const sampleWaitingPeriodExpired: WaitingPeriod = {
  kind: "initial",
  months: { value: 1, confidence: "high", provenance: pedWaitingProvenance, user_confirmed: true },
  applies_to: null,
  starts_on: "2026-01-01",
  expires_on: "2026-02-01",
};

const sampleWaitingPeriodMissingDates: WaitingPeriod = {
  kind: "maternity",
  months: { value: 24, confidence: "medium", provenance: null, user_confirmed: false },
  applies_to: null,
  starts_on: null,
  expires_on: null,
};

const samplePolicy: Policy = {
  id: "policy-sample",
  insurer: { id: "insurer-sample", name: "Kavach General Insurance", irdai_code: null },
  policy_number: "KHA/RTL/2026/004521",
  product_name: "Kavach Health Secure — Individual",
  policy_type: "individual",
  start_date: "2026-01-01",
  end_date: "2027-01-01",
  members: [],
  coverage_profile: {
    policy_id: "policy-sample",
    sum_insured: { value: 100000000, confidence: "high", provenance: roomRentProvenance, user_confirmed: true },
    co_pay_percent: { value: 10, confidence: "high", provenance: null, user_confirmed: true },
    sub_limits: sampleSubLimits,
    waiting_periods: [sampleWaitingPeriodActive],
    exclusions: [],
    intimation_deadline_hours: { value: 48, confidence: "high", provenance: null, user_confirmed: true },
    extraction_completeness: 0.82,
  },
  source_document_id: "doc-sample-policy",
};

const sampleAlerts: Alert[] = [
  {
    id: "alert-1",
    policy_id: "policy-sample",
    kind: "waiting_period_expiring",
    severity: "warning",
    title: "Pre-existing disease waiting period ends in 11 days",
    explanation: "After 2 Sep 2026, pre-existing conditions become claimable under your retail policy.",
    suggested_action: null,
    reference_source: null,
    triggers_on: "2026-09-02",
  },
  {
    id: "alert-2",
    policy_id: "policy-sample",
    kind: "no_maternity_cover",
    severity: "info",
    title: "Your employer policy excludes maternity",
    explanation: "The retail policy in this household covers maternity after 24 months — worth knowing if it matters to you.",
    suggested_action: "Compare the two policies",
    reference_source: null,
    triggers_on: null,
  },
  {
    id: "alert-3",
    policy_id: "policy-sample",
    kind: "low_sum_insured",
    severity: "critical",
    title: "Room rent choice may trigger a proportionate deduction",
    explanation: "A ₹12,000/day room is above your ₹5,000/day cap — insurers typically deduct proportionately across the whole bill, not just the room charge.",
    suggested_action: null,
    reference_source: "Estimate based on your policy's stated cap",
    triggers_on: null,
  },
];

function Section({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3 border-b border-rule pb-8">
      <div>
        <h2 className="font-serif text-xl font-semibold text-foreground">{title}</h2>
        {note && <p className="mt-0.5 text-sm text-muted-foreground">{note}</p>}
      </div>
      {children}
    </section>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5 sm:flex-row sm:items-center sm:gap-4">
      <span className="w-40 shrink-0 font-mono text-xs text-muted-foreground">{label}</span>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
    </div>
  );
}

export function KitchenSink() {
  const [activeProvenance, setActiveProvenance] = useState<Provenance | null>(null);
  const [errorRetryCount, setErrorRetryCount] = useState(0);

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-8 px-4 py-8 sm:px-6">
      <header className="flex flex-col gap-2 border-b-2 border-ink pb-4">
        <p className="font-mono text-xs tracking-wide text-muted-foreground uppercase">Dev route — not part of the product</p>
        <h1 className="font-serif text-3xl font-semibold text-foreground">Kitchen sink</h1>
        <p className="max-w-prose text-sm text-muted-foreground">
          Every primitive, in every state it can occupy — Phase 1's eleven plus the
          eight Phase 3 added while building the dashboard, policy list,
          upload/review, policy detail, and Q&A screens. To verify state is
          distinguishable without colour, screenshot this page and desaturate it —
          every row should still read correctly (icon + label carry the meaning).
        </p>
      </header>

      <Section title="Money" note="The only place ₹/Intl.NumberFormat('en-IN') appears. compact switches to lakh/crore above ₹1,00,000.">
        <Row label="small amount">
          <Money value={420000} />
        </Row>
        <Row label="large amount">
          <Money value={50000000} />
        </Row>
        <Row label="compact, lakh range">
          <Money value={50000000} compact />
        </Row>
        <Row label="compact, crore range">
          <Money value={1500000000} compact />
        </Row>
        <Row label="null">
          <Money value={null} />
        </Row>
      </Section>

      <Section title="ConfidenceBadge">
        <Row label="high">
          <ConfidenceBadge confidence="high" />
        </Row>
        <Row label="medium">
          <ConfidenceBadge confidence="medium" />
        </Row>
        <Row label="low">
          <ConfidenceBadge confidence="low" />
        </Row>
        <Row label="user confirmed">
          <ConfidenceBadge confidence="low" userConfirmed />
        </Row>
      </Section>

      <Section
        title="ProvenanceChip"
        note="Click a clickable chip to load it into the DocumentViewer below — this is the provenance click-through."
      >
        <Row label="verified">
          <ProvenanceChip provenance={roomRentProvenance} userConfirmed onOpen={setActiveProvenance} />
        </Row>
        <Row label="unconfirmed">
          <ProvenanceChip provenance={pedWaitingProvenance} userConfirmed={false} onOpen={setActiveProvenance} />
        </Row>
        <Row label="unverified (no source)">
          <ProvenanceChip provenance={null} onOpen={setActiveProvenance} />
        </Row>
        <Row label="page jump only, no bbox">
          <ProvenanceChip provenance={exclusionProvenanceNoBbox} userConfirmed onOpen={setActiveProvenance} />
        </Row>
      </Section>

      <Section
        title="ExtractedField"
        note="Every extracted value in the product renders through this — label, value, confidence, provenance, and (when correctable) inline confirm/correct controls, all in one shape."
      >
        <div className="flex flex-col gap-2">
          <ExtractedField
            label="Room rent cap (low confidence, correctable)"
            valueDisplay={<Money value={500000} />}
            confidence="low"
            userConfirmed={false}
            provenance={roomRentProvenance}
            snippet={roomRentProvenance.snippet}
            onOpenProvenance={setActiveProvenance}
            onConfirm={() => {}}
            onCorrect={() => {}}
            correctPlaceholder="Amount in rupees"
          />
          <ExtractedField
            label="Sum insured (confirmed)"
            valueDisplay={<Money value={1000000000} />}
            confidence="high"
            userConfirmed
            provenance={roomRentProvenance}
            onOpenProvenance={setActiveProvenance}
          />
          <ExtractedField
            label="Exclusion (read-only, no correction handlers)"
            valueDisplay={<span className="text-sm">Cosmetic surgery is excluded unless medically necessitated.</span>}
            confidence="medium"
            userConfirmed={false}
            provenance={null}
          />
        </div>
      </Section>

      <Section title="SubLimitsTable">
        <SubLimitsTable subLimits={sampleSubLimits} onOpenProvenance={setActiveProvenance} />
      </Section>

      <Section title="WaitingPeriodTimeline" note="A horizontal track showing months served vs remaining.">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <WaitingPeriodTimeline waitingPeriod={sampleWaitingPeriodActive} />
          <WaitingPeriodTimeline waitingPeriod={sampleWaitingPeriodExpired} />
          <WaitingPeriodTimeline waitingPeriod={sampleWaitingPeriodMissingDates} />
        </div>
      </Section>

      <Section title="PolicyCard">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <PolicyCard policy={samplePolicy} />
          <PolicyCard policy={samplePolicy} selectable={{ selected: true, onToggle: () => {} }} />
        </div>
      </Section>

      <Section title="JobProgress" note="The three-stage upload indicator — Uploading -> Parsing -> Review.">
        <div className="flex flex-col gap-4">
          <JobProgress stage="uploading" />
          <JobProgress stage="parsing" fileName="my-policy.pdf" pageCount={4} progressStep="extracting_tables" progressPercent={54} />
          <JobProgress stage="parsing" fileName="my-policy.pdf" stillWorking />
          <JobProgress stage="review" fileName="my-policy.pdf" />
        </div>
      </Section>

      <Section title="CitedProse" note="[[n]] markers in the source text become clickable superscripts.">
        <CitedProse
          text="Your policy caps room rent at the amount shown in your sub-limits table [[1]]. Choosing a room above that cap can trigger a proportionate deduction across your entire bill."
          citations={sampleCitations}
          onOpenCitation={(c) => c.provenance && setActiveProvenance(c.provenance)}
        />
      </Section>

      <Section title="FileDropzone">
        <FileDropzone onFileSelected={() => {}} />
      </Section>

      <Section title="AlertCard" note="Same four-tone system as VerdictBand/DeadlineCard, mapped from severity.">
        <div className="flex flex-col gap-2">
          {sampleAlerts.map((alert) => (
            <AlertCard key={alert.id} alert={alert} />
          ))}
        </div>
      </Section>

      <Section title="VerdictBand" note="No percentage, no gauge, no arc — a band and a sentence.">
        <div className="flex flex-col gap-2">
          <VerdictBand
            band="likely_eligible"
            explanation="All four checks against your policy's waiting periods and sub-limits are satisfied."
          />
          <VerdictBand
            band="at_risk"
            explanation="Your room rent choice is above your policy's cap, which may trigger a proportionate deduction."
          />
          <VerdictBand
            band="likely_ineligible"
            explanation="This admission falls inside your policy's pre-existing disease waiting period."
          />
          <VerdictBand
            band="insufficient_information"
            explanation="We can't check the pre-existing disease waiting period without your discharge summary."
          />
        </div>
      </Section>

      <Section title="DeadlineCard" note="Urgency drives treatment. Expired deadlines stay visible, not hidden.">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {sampleDeadlines.map((deadline) => (
            <DeadlineCard key={deadline.id} deadline={deadline} />
          ))}
        </div>
      </Section>

      <Section title="CitationList">
        <CitationList citations={sampleCitations} onOpenProvenance={(c) => c.provenance && setActiveProvenance(c.provenance)} />
      </Section>

      <Section
        title="DocumentViewer"
        note="Page-level jump degrades gracefully when a provenance has no bbox (see the ProvenanceChip row above)."
      >
        <Row label="active provenance">
          <span className="font-mono text-xs">
            {activeProvenance ? `page ${activeProvenance.page}, bbox ${activeProvenance.bbox ? "yes" : "no"}` : "none — click a chip above"}
          </span>
        </Row>
        <DocumentViewer fileUrl={SAMPLE_PDF} activeProvenance={activeProvenance} />

        <div className="mt-4 flex flex-col gap-3 border-t border-rule pt-4">
          <p className="text-xs text-muted-foreground">Other DocumentViewer states:</p>
          <Row label="empty (no document)">
            <DocumentViewer fileUrl={null} className="w-full" />
          </Row>
          <Row label="error → retry (genuinely re-fetches a file that doesn't exist)">
            <div className="w-full">
              <DocumentViewer fileUrl="/kitchen-sink/does-not-exist.pdf" />
            </div>
          </Row>
        </div>
      </Section>

      <Section title="Skeleton">
        <div className="flex max-w-sm flex-col gap-2">
          <Skeleton className="h-6 w-2/3" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-5/6" />
          <Skeleton className="h-24 w-full" />
        </div>
      </Section>

      <Section title="EmptyState">
        <EmptyState
          title="No policies yet"
          description="Upload a policy document to see its coverage profile here."
          action={{ label: "Upload a policy", onClick: () => {} }}
        />
      </Section>

      <Section title="ErrorState" note="Retry actually retries — the counter below proves the callback fires.">
        <p className="font-mono text-xs text-muted-foreground">Retries: {errorRetryCount}</p>
        <ErrorState
          message="We couldn't load your claims. Check your connection and try again."
          requestId="01J8XA2QK7Z9"
          onRetry={() => setErrorRetryCount((n) => n + 1)}
        />
      </Section>

      <Section title="AbstentionCard" note="Styled as information, never as an error.">
        <AbstentionCard
          missingFact="We can't confirm your maternity waiting period."
          resolvingDocument="Policy wording (full terms document)"
          action={{ label: "Upload policy wording", onClick: () => {} }}
        />
      </Section>
    </div>
  );
}
