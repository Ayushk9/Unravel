import { useState, type ReactNode } from "react";
import type { Citation, Deadline, Provenance } from "@/api/types";
import {
  AbstentionCard,
  CitationList,
  ConfidenceBadge,
  DeadlineCard,
  DocumentViewer,
  EmptyState,
  ErrorState,
  Money,
  ProvenanceChip,
  Skeleton,
  VerdictBand,
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
          Every Phase 1 primitive, in every state it can occupy. To verify state is
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
