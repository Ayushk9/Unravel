import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { AlertTriangle, Check, CheckSquare, Copy, FileSignature, ShieldCheck, Square } from "lucide-react";
import type { Citation, GrievanceDraft, GrievanceRungOption, Provenance } from "@/api/types";
import { confirmationSummary, defaultRung, type DraftRung } from "@/lib/grievance";
import { ApiError } from "@/api/client";
import { grievanceDraftSchema } from "@/api/schemas";
import { useClaim, useGrievanceRungs, useRequestGrievanceDraft } from "@/api/endpoints/claims";
import { useJobPolling } from "@/api/endpoints/jobs";
import { usePolicy } from "@/api/endpoints/policies";
import { useDocumentFile } from "@/api/endpoints/documents";
import { AbstentionCard, DocumentViewer, EmptyState, ErrorState, Skeleton } from "@/components/primitives";

// Product rule 4: the exact words a flagged paragraph carries.
const UNVERIFIED_FLAG = "We couldn't confirm this against your documents. Check or remove it before sending.";
const SCREEN_DISCLAIMER = "This is a draft based on your documents, not legal advice. You review it and send it yourself; the app never sends anything.";

const STEP_LABEL: Record<string, string> = {
  queued: "Waiting to start",
  retrieving: "Finding the clauses of your policy that bear on this claim",
  drafting: "Drafting the argument",
  verifying: "Checking every paragraph against your policy",
  done: "Done",
};

type Rung = DraftRung;

/**
 * Feature 7: draft a grievance letter for one rung of the escalation ladder.
 * The letter's facts (header, dates, amounts, pages) come from the server's
 * code; only the argument paragraphs were written by a model, and any it
 * couldn't confirm against the policy are flagged, never hidden.
 */
export function ClaimGrievance() {
  const { id } = useParams<{ id: string }>();
  const claimId = id ?? null;
  const [searchParams, setSearchParams] = useSearchParams();
  const jobId = searchParams.get("job");
  const rungParam = searchParams.get("rung");

  const claim = useClaim(claimId);
  const policy = usePolicy(claim.data?.policy_id ?? null);
  const rungs = useGrievanceRungs(claimId);
  const request = useRequestGrievanceDraft(claimId ?? "");
  const job = useJobPolling(jobId, grievanceDraftSchema);

  const available = (rungs.data ?? []).filter((r) => r.available && r.rung !== "other");
  const [chosen, setChosen] = useState<Rung | null>(null);
  const selected: Rung | null = chosen ?? defaultRung(rungs.data ?? [], rungParam);

  const [activeProvenance, setActiveProvenance] = useState<Provenance | null>(null);
  const viewedFile = useDocumentFile(activeProvenance?.document_id ?? policy.data?.source_document_id ?? null);

  function generate() {
    if (!selected) return;
    // A new key per click: each click is a new draft. A retried network request reuses nothing (D-13).
    request.mutate(
      { rung: selected, idempotencyKey: crypto.randomUUID() },
      { onSuccess: (accepted) => setSearchParams({ rung: selected, job: accepted.job_id }) },
    );
  }

  const running = jobId !== null && (job.isPending || (job.data && job.data.status !== "succeeded" && job.data.status !== "failed"));

  return (
    <div className="flex flex-col gap-6 lg:flex-row">
      <div className="flex min-w-0 flex-1 flex-col gap-6">
        <header className="flex flex-col gap-1">
          <Link to={claimId ? `/claims/${claimId}` : "/claims"} className="text-sm text-muted-foreground hover:text-foreground">
            ← Back to the claim
          </Link>
          <h1 className="font-serif text-2xl font-semibold text-foreground">Draft a grievance letter</h1>
          {claim.data && <p className="text-sm text-muted-foreground">{claim.data.hospital_name}</p>}
        </header>

        <Disclaimer text={SCREEN_DISCLAIMER} />

        <section className="flex flex-col gap-3" aria-labelledby="rung-heading">
          <h2 id="rung-heading" className="font-serif text-lg font-semibold text-foreground">
            Who is the letter to?
          </h2>
          {rungs.isPending ? (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-16 w-full" />
            </div>
          ) : rungs.isError ? (
            <ErrorState message="We couldn't load the options for this claim. Check your connection and try again." onRetry={() => rungs.refetch()} />
          ) : available.length === 0 ? (
            <EmptyState
              icon={FileSignature}
              title="No letter fits this claim yet"
              description={(rungs.data ?? []).map((r) => `${r.label}: ${r.reason}`).join(" ")}
            />
          ) : (
            <RungSelector options={rungs.data ?? []} selected={selected} onSelect={setChosen} />
          )}
        </section>

        {available.length > 0 && (
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={generate}
              disabled={!selected || request.isPending || Boolean(running)}
              className="inline-flex items-center gap-1.5 rounded bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
            >
              <FileSignature className="size-4" aria-hidden="true" />
              {job.data?.status === "succeeded" ? "Generate again" : "Generate draft"}
            </button>
            <span className="text-xs text-muted-foreground">Takes up to a minute. Each draft is written fresh.</span>
          </div>
        )}

        {request.isError && (
          <ErrorState
            message={request.error instanceof ApiError ? request.error.message : "We couldn't start the draft. Try again."}
            onRetry={generate}
          />
        )}

        {running && (
          <div role="status" className="flex items-center gap-3 rounded border border-rule bg-card px-4 py-3">
            <Skeleton className="h-4 w-4 rounded-full" />
            <span className="text-sm text-muted-foreground">
              {job.timedOut
                ? "Still working — this is taking longer than usual. You can come back to this page later."
                : STEP_LABEL[job.data?.progress?.step ?? "queued"] ?? "Working"}
            </span>
          </div>
        )}
        {running && <LetterSkeleton />}

        {job.isError && <ErrorState message="We couldn't check on the draft. Try again." onRetry={() => job.refetch()} />}
        {job.data?.status === "failed" && <ErrorState message={job.data.error ?? "We couldn't draft the letter. Try again."} onRetry={generate} />}

        {job.data?.status === "succeeded" && job.data.result && (
          <DraftView draft={job.data.result} onOpenCitation={(c) => c.provenance && setActiveProvenance(c.provenance)} />
        )}
      </div>

      <aside className="w-full shrink-0 lg:w-96">
        <DocumentViewer fileUrl={viewedFile.data?.url ?? null} activeProvenance={activeProvenance} className="sticky top-4" />
      </aside>
    </div>
  );
}

function Disclaimer({ text }: { text: string }) {
  return (
    <p role="note" className="rounded border border-neutral-border bg-neutral-bg px-4 py-2 text-sm text-foreground">
      {text}
    </p>
  );
}

function RungSelector({
  options,
  selected,
  onSelect,
}: {
  options: GrievanceRungOption[];
  selected: Rung | null;
  onSelect: (rung: Rung) => void;
}) {
  return (
    <div role="radiogroup" aria-label="Escalation step" className="flex flex-col gap-2">
      {options
        .filter((o) => o.rung !== "other")
        .map((option) => {
          const isSelected = option.rung === selected;
          return (
            <button
              key={option.rung}
              type="button"
              role="radio"
              aria-checked={isSelected}
              disabled={!option.available}
              onClick={() => onSelect(option.rung as Rung)}
              className={`flex flex-col gap-1 rounded border px-4 py-3 text-left disabled:cursor-not-allowed disabled:opacity-60 ${
                isSelected ? "border-stamp bg-positive-bg" : "border-rule bg-card hover:bg-secondary"
              }`}
            >
              <span className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-foreground">{option.label}</span>
                {!option.available && <span className="text-xs text-muted-foreground">Not yet</span>}
                {option.available && !option.verified && (
                  <span className="inline-flex items-center gap-1 rounded border border-caution-border bg-caution-bg px-1.5 py-0.5 text-xs font-medium text-caution">
                    <AlertTriangle className="size-3" aria-hidden="true" />
                    Based on an unverified rule
                  </span>
                )}
              </span>
              <span className="text-sm text-muted-foreground">{option.reason}</span>
            </button>
          );
        })}
    </div>
  );
}

function LetterSkeleton() {
  return (
    <div className="flex flex-col gap-3 rounded border border-rule bg-card p-5" aria-hidden="true">
      <Skeleton className="h-4 w-1/2" />
      <Skeleton className="h-4 w-3/4" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-24 w-full" />
    </div>
  );
}

function DraftView({ draft, onOpenCitation }: { draft: GrievanceDraft; onOpenCitation: (citation: Citation) => void }) {
  const [copied, setCopied] = useState(false);
  const summary = confirmationSummary(draft.paragraphs);
  const byId = new Map(draft.citations.map((c) => [c.id, c]));

  async function copy() {
    try {
      await navigator.clipboard.writeText(draft.letter_text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <section className="flex flex-col gap-4" aria-label="Draft letter">
      {/* A count, never a percentage or gauge (product rule 2). */}
      {summary && (
        <div
          className={`flex items-center gap-2 rounded border px-4 py-2 text-sm ${
            summary.confirmed === summary.total ? "border-positive-border bg-positive-bg" : "border-caution-border bg-caution-bg"
          }`}
        >
          {summary.confirmed === summary.total ? (
            <ShieldCheck className="size-4 text-stamp" aria-hidden="true" />
          ) : (
            <AlertTriangle className="size-4 text-caution" aria-hidden="true" />
          )}
          <span className="text-foreground">{summary.text}</span>
        </div>
      )}

      {/* D-47: our rules agree with the denial, so the letter asks for an explanation instead of disputing it. */}
      {draft.assessment_note && (
        <p role="note" className="rounded border border-neutral-border bg-neutral-bg px-4 py-2 text-sm text-foreground">
          {draft.assessment_note}
        </p>
      )}

      {draft.missing_context && <AbstentionCard missingFact={draft.missing_context} resolvingDocument="Your full policy wording document" />}

      <article className="flex flex-col gap-4 rounded border border-rule bg-card p-5 text-sm leading-relaxed text-foreground">
        <div>
          <p className="text-muted-foreground">To,</p>
          <p className="font-medium">{draft.addressee}</p>
        </div>
        <p>
          <span className="font-semibold">Subject:</span> {draft.subject}
        </p>
        <dl className="grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-[max-content_1fr]">
          {draft.header_lines.map((line) => (
            <div key={line.label} className="contents">
              <dt className="text-muted-foreground">{line.label}</dt>
              <dd className={line.value ? "" : "italic text-muted-foreground"}>{line.value ?? "not recorded"}</dd>
            </div>
          ))}
        </dl>
        <p>Dear Sir or Madam,</p>

        {draft.paragraphs.length === 0 && (
          <p className="rounded border border-dashed border-rule px-3 py-2 italic text-muted-foreground">
            Write here why you disagree with the decision. We couldn't draft this part from your policy's text.
          </p>
        )}
        {draft.paragraphs.map((paragraph, index) =>
          paragraph.source === "template" ? (
            // Our fixed procedural request (D-47): no model output and no claim about the policy, so no flag and no citation.
            <div key={index} className="flex flex-col gap-1">
              <span className="text-xs tracking-wide text-muted-foreground uppercase">Standard request (template text)</span>
              <p>{paragraph.text}</p>
            </div>
          ) : (
          <div
            key={index}
            className={paragraph.verified ? "" : "flex flex-col gap-2 rounded border-l-4 border-caution-border bg-caution-bg py-2 pr-2 pl-3"}
          >
            {!paragraph.verified && (
              <p className="inline-flex items-start gap-1.5 text-xs font-semibold text-caution">
                <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
                {UNVERIFIED_FLAG}
              </p>
            )}
            <p>{paragraph.text}</p>
            <span className="mt-1 flex flex-wrap gap-1.5">
              {paragraph.citation_ids.map((citationId) => {
                const citation = byId.get(citationId);
                if (!citation) return null;
                return (
                  <button
                    key={citationId}
                    type="button"
                    onClick={() => onOpenCitation(citation)}
                    className="rounded-full border border-rule bg-background px-2 py-0.5 text-xs text-muted-foreground hover:text-foreground"
                  >
                    Policy, {citation.label.toLowerCase()}
                  </button>
                );
              })}
            </span>
          </div>
          ),
        )}

        <p className="whitespace-pre-line">{draft.closing}</p>
        <p className="border-t border-rule pt-3 text-xs text-muted-foreground">{draft.disclaimer}</p>
      </article>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => void copy()}
          className="inline-flex items-center gap-1.5 rounded border border-rule bg-card px-3 py-1.5 text-sm font-medium text-foreground hover:bg-secondary"
        >
          {copied ? <Check className="size-4" aria-hidden="true" /> : <Copy className="size-4" aria-hidden="true" />}
          {copied ? "Copied" : "Copy text"}
        </button>
        <span className="text-xs text-muted-foreground">Flagged paragraphs are copied with a warning line, so you can find them.</span>
      </div>

      <section className="flex flex-col gap-2" aria-labelledby="evidence-heading">
        <h2 id="evidence-heading" className="font-serif text-lg font-semibold text-foreground">
          Evidence to attach
        </h2>
        {draft.evidence_checklist.length === 0 ? (
          <p className="text-sm text-muted-foreground">We don't have a document checklist for this type of claim.</p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {draft.evidence_checklist.map((item) => (
              <li key={item.item} className="flex items-center gap-2 text-sm">
                {item.satisfied ? (
                  <CheckSquare className="size-4 text-stamp" aria-label="Attached" />
                ) : (
                  <Square className="size-4 text-ink-muted" aria-label="Not attached yet" />
                )}
                <span className={item.satisfied ? "text-foreground" : "text-muted-foreground"}>{item.item}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </section>
  );
}
