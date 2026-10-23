import { useState, type FormEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { FileSignature } from "lucide-react";
import type { Claim, ClaimState, Policy, Provenance, StoredDocument } from "@/api/types";
import { ApiError } from "@/api/client";
import { useAppendClaimEvent, useClaim, useEligibility } from "@/api/endpoints/claims";
import { useClaimDocuments, useCorrectDocumentType, useDeleteDocument, useUploadDocument } from "@/api/endpoints/documents";
import { useJobPolling } from "@/api/endpoints/jobs";
import { usePolicy } from "@/api/endpoints/policies";
import { useMembers } from "@/api/endpoints/members";
import { parseDocumentResultSchema } from "@/api/schemas";
import { localDateTimeToIsoIst, nowIsoIst } from "@/lib/formatDate";
import {
  ClaimEventItem,
  ClaimStateBadge,
  claimStateLabel,
  DeadlineCard,
  DocumentRow,
  EligibilityAssessmentView,
  EmptyState,
  ErrorState,
  FileDropzone,
  Modal,
  Skeleton,
} from "@/components/primitives";
import { insurerLabel, productLabel } from "@/lib/policyLabels";
import { ProvenanceModal } from "@/components/ProvenanceModal";
import { ClaimFactsForm } from "@/components/ClaimFactsForm";

const TABS: { key: string; label: string }[] = [
  { key: "timeline", label: "Timeline" },
  { key: "eligibility", label: "Eligibility" },
  { key: "documents", label: "Documents" },
  { key: "bill", label: "Bill" },
];

export function ClaimWorkspace() {
  const { id } = useParams<{ id: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = searchParams.get("tab") ?? "timeline";

  const claim = useClaim(id ?? null);
  const policy = usePolicy(claim.data?.policy_id ?? null);
  const members = useMembers();
  const member = (members.data ?? []).find((m) => m.id === claim.data?.member_id) ?? null;

  function switchTab(next: string) {
    setSearchParams({ tab: next });
  }

  if (claim.isPending) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }
  if (claim.isError || !claim.data) {
    return <ErrorState message="We couldn't load this claim. Check your connection and try again." onRetry={() => claim.refetch()} />;
  }

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-serif text-2xl font-semibold text-foreground">{claim.data.hospital_name}</h1>
          <p className="text-sm text-muted-foreground">
            {policy.data ? `${insurerLabel(policy.data)} — ${productLabel(policy.data)}` : "—"}
            {member ? ` · ${member.full_name}` : ""}
          </p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <ClaimStateBadge state={claim.data.current_state} />
          {/* Feature 7: a letter is worth drafting once the insurer has said no, or the user has already complained. */}
          {["denied", "grievance_sent", "insurer_replied", "escalated"].includes(claim.data.current_state) && (
            <Link
              to={`/claims/${claim.data.id}/grievance`}
              className="inline-flex items-center gap-1.5 rounded border border-rule bg-card px-3 py-1.5 text-sm font-medium text-foreground hover:bg-secondary"
            >
              <FileSignature className="size-4" aria-hidden="true" />
              Draft a grievance letter
            </Link>
          )}
        </div>
      </header>

      <div role="tablist" aria-label="Claim workspace" className="flex gap-1 border-b border-rule">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => switchTab(t.key)}
            className={`rounded-t px-3 py-2 text-sm font-medium ${
              tab === t.key ? "border-b-2 border-stamp text-stamp" : "text-ink-muted hover:text-foreground"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "timeline" && <TimelineTab claim={claim.data} />}
      {tab === "eligibility" && <EligibilityTab claim={claim.data} policy={policy.data ?? null} onGoToDocuments={() => switchTab("documents")} />}
      {tab === "documents" && <DocumentsTab claimId={claim.data.id} />}
      {tab === "bill" && <BillTab />}
    </div>
  );
}

// --- Timeline tab ---

function TimelineTab({ claim }: { claim: Claim }) {
  const [modalOpen, setModalOpen] = useState(false);
  const events = [...claim.events].reverse();

  return (
    <div className="flex flex-col gap-6">
      {claim.deadlines.length > 0 && (
        <section className="flex flex-col gap-2">
          <h2 className="font-serif text-lg font-semibold text-foreground">Deadlines</h2>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {claim.deadlines.map((d) => (
              <DeadlineCard key={d.id} deadline={d} />
            ))}
          </div>
        </section>
      )}

      {/* D-33: a deadline that could not be worked out is named, with the reason, rather than guessed or hidden. */}
      {claim.omitted_deadlines.length > 0 && (
        <section className="flex flex-col gap-2">
          <h2 className="font-serif text-base font-semibold text-foreground">Deadlines we couldn't work out</h2>
          <ul className="flex flex-col gap-2">
            {claim.omitted_deadlines.map((omitted) => (
              <li key={omitted.id} className="rounded border border-neutral-border bg-neutral-bg px-4 py-3 text-sm">
                <span className="font-semibold text-foreground">{omitted.label}</span>
                <span className="block text-xs text-muted-foreground">{omitted.reason}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h2 className="font-serif text-lg font-semibold text-foreground">Event log</h2>
          <button
            type="button"
            onClick={() => setModalOpen(true)}
            className="rounded border border-rule px-3 py-1.5 text-sm font-medium text-foreground hover:bg-secondary"
          >
            Add event
          </button>
        </div>
        <ol className="flex flex-col">
          {events.map((event, i) => (
            <ClaimEventItem key={event.id} event={event} isLast={i === events.length - 1} />
          ))}
        </ol>
      </section>

      <AddEventModal claimId={claim.id} open={modalOpen} onClose={() => setModalOpen(false)} />
    </div>
  );
}

const CLAIM_STATE_OPTIONS: ClaimState[] = [
  "intimated",
  "documents_submitted",
  "under_review",
  "queried",
  "approved",
  "denied",
  "grievance_sent",
  "insurer_replied",
  "escalated",
  "resolved",
];

/** Append-only log — adding an event is a deliberate modal action, never an inline edit. A 409 re-renders the allowed target states inline rather than a generic error toast. */
function AddEventModal({ claimId, open, onClose }: { claimId: string; open: boolean; onClose: () => void }) {
  const [toState, setToState] = useState<ClaimState>("documents_submitted");
  const [occurredAt, setOccurredAt] = useState(() => nowIsoIst().slice(0, 16));
  const [note, setNote] = useState("");
  const [allowedStates, setAllowedStates] = useState<ClaimState[] | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const mutation = useAppendClaimEvent(claimId);

  function resetForm() {
    setToState("documents_submitted");
    setOccurredAt(nowIsoIst().slice(0, 16));
    setNote("");
    setAllowedStates(null);
    setErrorMessage(null);
  }

  function handleClose() {
    resetForm();
    onClose();
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setErrorMessage(null);
    mutation.mutate(
      { to_state: toState, occurred_at: localDateTimeToIsoIst(occurredAt), note: note.trim() || null },
      {
        onSuccess: () => handleClose(),
        onError: (err) => {
          if (err instanceof ApiError && err.code === "illegal_transition") {
            setAllowedStates(err.fieldErrors.map((fe) => fe.message as ClaimState));
          } else {
            setErrorMessage(err instanceof Error ? err.message : "Couldn't log that event. Try again.");
          }
        },
      },
    );
  }

  return (
    <Modal open={open} onClose={handleClose} title="Log a new event">
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">New state</span>
          <select
            value={toState}
            onChange={(e) => setToState(e.target.value as ClaimState)}
            className="rounded border border-rule bg-background px-2 py-1.5 text-sm"
          >
            {CLAIM_STATE_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {claimStateLabel[s]}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">When</span>
          <input
            type="datetime-local"
            value={occurredAt}
            onChange={(e) => setOccurredAt(e.target.value)}
            required
            className="rounded border border-rule bg-background px-2 py-1.5 text-sm"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">Note (optional)</span>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
            className="rounded border border-rule bg-background px-2 py-1.5 text-sm"
          />
        </label>

        {allowedStates && (
          <div className="flex flex-col gap-2 rounded border border-caution-border bg-caution-bg px-3 py-2.5">
            <p className="text-sm text-caution">That transition isn't allowed from the claim's current state. Try one of these instead:</p>
            {allowedStates.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {allowedStates.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => {
                      setToState(s);
                      setAllowedStates(null);
                    }}
                    className="rounded border border-caution-border bg-card px-2 py-1 text-xs font-medium text-caution hover:bg-caution-bg"
                  >
                    {claimStateLabel[s]}
                  </button>
                ))}
              </div>
            ) : (
              <p className="text-xs text-caution">This claim has no further transitions available.</p>
            )}
          </div>
        )}

        {errorMessage && <p className="text-sm text-flag">{errorMessage}</p>}

        <div className="mt-1 flex justify-end gap-2">
          <button type="button" onClick={handleClose} className="rounded border border-rule px-3 py-1.5 text-sm">
            Cancel
          </button>
          <button
            type="submit"
            disabled={mutation.isPending}
            className="rounded bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            {mutation.isPending ? "Saving…" : "Log event"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

// --- Eligibility tab ---

function EligibilityTab({ claim, policy, onGoToDocuments }: { claim: Claim; policy: Policy | null; onGoToDocuments: () => void }) {
  const [viewerProvenance, setViewerProvenance] = useState<Provenance | null>(null);
  const eligibility = useEligibility(claim.id);
  const anyUnanswered = Object.entries(claim.facts).some(([key, value]) => key !== "diagnosis" && value === null);

  const factsSection = (
    // Open while something is unanswered, so the missing facts can be answered right here.
    <details open={anyUnanswered} className="rounded border border-rule bg-card px-4 py-3">
      <summary className="cursor-pointer font-serif text-base font-semibold text-foreground">About this illness and stay</summary>
      <div className="mt-3">
        <ClaimFactsForm claim={claim} policy={policy} />
      </div>
    </details>
  );

  if (eligibility.isPending) return <Skeleton className="h-64 w-full" />;
  if (eligibility.isError) {
    return <ErrorState message="We couldn't assess this claim. Check your connection and try again." onRetry={() => eligibility.refetch()} />;
  }

  return (
    <div className="flex flex-col gap-4">
      {factsSection}
      <EligibilityAssessmentView assessment={eligibility.data} onOpenProvenance={setViewerProvenance} onUploadResolvingDocument={onGoToDocuments} />
      <ProvenanceModal provenance={viewerProvenance} onClose={() => setViewerProvenance(null)} title="Governing clause" />
    </div>
  );
}

// --- Documents tab ---

function ConnectedDocumentRow({ document, onView }: { document: StoredDocument; onView: () => void }) {
  const correctType = useCorrectDocumentType(document.id);
  const deleteDocument = useDeleteDocument();

  return (
    <DocumentRow
      document={document}
      pending={correctType.isPending || deleteDocument.isPending}
      onTypeChange={(t) => correctType.mutate(t)}
      onView={onView}
      onDelete={() => {
        if (window.confirm(`Remove ${document.file_name}? You can re-upload it later if needed.`)) {
          deleteDocument.mutate(document.id);
        }
      }}
    />
  );
}

/** Renders nothing — its only job is to keep polling GET /jobs/{id} until the parse_document job resolves, which is what actually flips the document's parse_status server-side (D-07). */
function ParseJobPoller({ jobId }: { jobId: string }) {
  useJobPolling(jobId, parseDocumentResultSchema);
  return null;
}

function DocumentsTab({ claimId }: { claimId: string }) {
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [viewerProvenance, setViewerProvenance] = useState<Provenance | null>(null);
  const [pendingJobIds, setPendingJobIds] = useState<string[]>([]);
  const claimDocs = useClaimDocuments(claimId);
  const uploadDocument = useUploadDocument();

  function handleFileSelected(file: File) {
    setUploadError(null);
    const idempotencyKey = crypto.randomUUID();
    uploadDocument.mutate(
      { file, claimId, idempotencyKey },
      {
        onSuccess: (job) => setPendingJobIds((ids) => [...ids, job.job_id]),
        onError: (err) => setUploadError(err instanceof Error ? err.message : "Upload failed. Try again."),
      },
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {claimDocs.isPending && <Skeleton className="h-24 w-full" />}
      {claimDocs.isError && (
        <ErrorState message="We couldn't load this claim's documents. Check your connection and try again." onRetry={() => claimDocs.refetch()} />
      )}
      {claimDocs.isSuccess && claimDocs.data.length === 0 && (
        <EmptyState title="No documents yet" description="Upload the documents this claim needs — we'll auto-detect each one's type." />
      )}
      {claimDocs.isSuccess && claimDocs.data.length > 0 && (
        <div className="flex flex-col gap-2">
          {claimDocs.data.map((doc) => (
            <ConnectedDocumentRow
              key={doc.id}
              document={doc}
              onView={() => setViewerProvenance({ document_id: doc.id, page: 1, bbox: null, snippet: null })}
            />
          ))}
        </div>
      )}

      <FileDropzone onFileSelected={handleFileSelected} />
      {uploadDocument.isPending && <p className="text-sm text-muted-foreground">Uploading…</p>}
      {uploadError && <p className="text-sm text-flag">{uploadError}</p>}
      {pendingJobIds.map((jobId) => (
        <ParseJobPoller key={jobId} jobId={jobId} />
      ))}

      <ProvenanceModal provenance={viewerProvenance} onClose={() => setViewerProvenance(null)} title="Document preview" />
    </div>
  );
}

// --- Bill tab (stub — Feature 3 lands in Phase 5) ---

function BillTab() {
  return (
    <EmptyState
      title="Bill validation lands in Phase 5"
      description="Extracted line items, flagged charges, and the amount at risk will show up here once bill validation is built."
    />
  );
}
