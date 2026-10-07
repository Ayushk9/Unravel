import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import type { Claim, Provenance, StoredDocument } from "@/api/types";
import { usePolicies, usePolicy } from "@/api/endpoints/policies";
import { useMembers } from "@/api/endpoints/members";
import { useAppendClaimEvent, useBillValidation, useClaim, useCompleteness, useCreateClaim, useEligibility } from "@/api/endpoints/claims";
import { useClaimDocuments, useCorrectDocumentType, useDeleteDocument, useUploadDocument } from "@/api/endpoints/documents";
import { useJobPolling } from "@/api/endpoints/jobs";
import { parseDocumentResultSchema } from "@/api/schemas";
import { nowIsoIst } from "@/lib/formatDate";
import {
  CompletenessPanel,
  DocumentRow,
  DocumentViewer,
  EligibilityAssessmentView,
  EmptyState,
  ErrorState,
  FileDropzone,
  Modal,
  Money,
  Skeleton,
  WizardSteps,
  type WizardStep,
} from "@/components/primitives";
import { insurerLabel, policyNumberLabel, productLabel } from "@/lib/policyLabels";

/** Same mock limitation as /policies/upload and /policies/:id — see DECISIONS.md. */
const MOCK_SOURCE_PDF = "/kitchen-sink/sample-policy.pdf";

const STEPS: WizardStep[] = [
  { key: "policy", label: "Policy & member" },
  { key: "details", label: "Claim details" },
  { key: "documents", label: "Documents" },
  { key: "bill", label: "Bill review" },
  { key: "eligibility", label: "Eligibility" },
  { key: "summary", label: "Summary" },
];

/**
 * Resumable via the URL, never localStorage (binding constraint): `policy` /
 * `member` are lifted to search params from step 1 since they're cheap id
 * references, and once step 2 creates the claim, `claim` + `step` are all a
 * refresh needs to resume from — everything from step 3 onward reads back
 * from the server. Step 2's free-form fields (hospital name, dates, amount)
 * are *not* mirrored to the URL; a refresh before the claim exists restarts
 * intake at step 1, the same degradation /policies/upload accepts for a
 * refresh before its upload begins. See DECISIONS.md.
 */
export function ClaimNew() {
  const [searchParams, setSearchParams] = useSearchParams();

  const claimId = searchParams.get("claim");
  const step = Math.min(6, Math.max(1, Number.parseInt(searchParams.get("step") ?? "1", 10) || 1));
  const policyIdParam = searchParams.get("policy");
  const memberIdParam = searchParams.get("member");

  const claimQuery = useClaim(claimId);

  useEffect(() => {
    if (step >= 3 && !claimId) {
      setSearchParams({ step: "1" });
    }
  }, [step, claimId, setSearchParams]);

  function updateParams(patch: Record<string, string | null>) {
    const next = new URLSearchParams(searchParams);
    for (const [k, v] of Object.entries(patch)) {
      if (v === null) next.delete(k);
      else next.set(k, v);
    }
    setSearchParams(next);
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <header>
        <h1 className="font-serif text-2xl font-semibold text-foreground">File a claim</h1>
        <p className="text-sm text-muted-foreground">Six steps — leave and come back any time, your progress is saved.</p>
      </header>

      <WizardSteps steps={STEPS} currentIndex={step - 1} />

      {step === 1 && (
        <StepPolicyMember
          policyId={policyIdParam}
          memberId={memberIdParam}
          onSelectPolicy={(id) => updateParams({ policy: id, member: null })}
          onSelectMember={(id) => updateParams({ member: id })}
          onNext={() => updateParams({ step: "2" })}
        />
      )}

      {step === 2 && policyIdParam && memberIdParam && (
        <StepClaimDetails
          policyId={policyIdParam}
          memberId={memberIdParam}
          onBack={() => updateParams({ step: "1" })}
          onCreated={(claim) => updateParams({ claim: claim.id, step: "3" })}
        />
      )}

      {step >= 3 && claimId && (
        <>
          {claimQuery.isPending && <Skeleton className="h-48 w-full" />}
          {claimQuery.isError && (
            <ErrorState message="We couldn't load this claim. Check your connection and try again." onRetry={() => claimQuery.refetch()} />
          )}
          {claimQuery.isSuccess && (
            <>
              {step === 3 && <StepDocuments claimId={claimId} onNext={() => updateParams({ step: "4" })} />}
              {step === 4 && (
                <StepBillReview claimId={claimId} onNext={() => updateParams({ step: "5" })} onBack={() => updateParams({ step: "3" })} />
              )}
              {step === 5 && (
                <StepEligibility
                  claimId={claimId}
                  onNext={() => updateParams({ step: "6" })}
                  onBack={() => updateParams({ step: "4" })}
                  onGoToDocuments={() => updateParams({ step: "3" })}
                />
              )}
              {step === 6 && <StepSummary claim={claimQuery.data} onBack={() => updateParams({ step: "5" })} />}
            </>
          )}
        </>
      )}
    </div>
  );
}

// --- Step 1: policy + member ---

function StepPolicyMember({
  policyId,
  memberId,
  onSelectPolicy,
  onSelectMember,
  onNext,
}: {
  policyId: string | null;
  memberId: string | null;
  onSelectPolicy: (id: string) => void;
  onSelectMember: (id: string) => void;
  onNext: () => void;
}) {
  const navigate = useNavigate();
  const policies = usePolicies();

  if (policies.isPending) {
    return (
      <div className="flex flex-col gap-2">
        <Skeleton className="h-14 w-full" />
        <Skeleton className="h-14 w-full" />
      </div>
    );
  }
  if (policies.isError) {
    return <ErrorState message="We couldn't load your policies. Check your connection and try again." onRetry={() => policies.refetch()} />;
  }
  if (policies.data.length === 0) {
    return (
      <EmptyState
        title="No policies to claim against"
        description="Upload a policy first — we'll extract its coverage terms so we can check this claim against them."
        action={{ label: "Upload a policy", onClick: () => navigate("/policies/upload") }}
      />
    );
  }

  const selectedPolicy = policies.data.find((p) => p.id === policyId) ?? null;

  return (
    <div className="flex flex-col gap-5">
      <section className="flex flex-col gap-2">
        <h2 className="font-serif text-lg font-semibold text-foreground">Which policy is this claim against?</h2>
        <div className="flex flex-col gap-2">
          {policies.data.map((p) => (
            <label
              key={p.id}
              className={`flex cursor-pointer items-center gap-3 rounded border px-3 py-2.5 ${
                policyId === p.id ? "border-stamp ring-1 ring-stamp" : "border-rule"
              }`}
            >
              <input type="radio" name="policy" checked={policyId === p.id} onChange={() => onSelectPolicy(p.id)} className="size-4 accent-stamp" />
              <div className="flex flex-col">
                <span className="font-serif text-sm font-semibold text-foreground">
                  {insurerLabel(p)} — {productLabel(p)}
                </span>
                <span className="text-xs text-muted-foreground">Policy {policyNumberLabel(p)}</span>
              </div>
            </label>
          ))}
        </div>
      </section>

      {selectedPolicy && (
        <section className="flex flex-col gap-2">
          <h2 className="font-serif text-lg font-semibold text-foreground">Who is this claim for?</h2>
          <div className="flex flex-col gap-2">
            {selectedPolicy.members.map((m) => (
              <label
                key={m.id}
                className={`flex cursor-pointer items-center gap-3 rounded border px-3 py-2.5 ${
                  memberId === m.id ? "border-stamp ring-1 ring-stamp" : "border-rule"
                }`}
              >
                <input type="radio" name="member" checked={memberId === m.id} onChange={() => onSelectMember(m.id)} className="size-4 accent-stamp" />
                <span className="text-sm font-medium text-foreground">
                  {m.full_name} <span className="text-xs font-normal text-muted-foreground">({m.relationship})</span>
                </span>
              </label>
            ))}
          </div>
        </section>
      )}

      <button
        type="button"
        disabled={!policyId || !memberId}
        onClick={onNext}
        className="w-fit rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/85 disabled:opacity-50"
      >
        Next
      </button>
    </div>
  );
}

// --- Step 2: claim type, admission type, case details ---

const CLAIM_TYPE_OPTIONS: { value: Claim["claim_type"]; label: string }[] = [
  { value: "reimbursement", label: "Reimbursement" },
  { value: "cashless", label: "Cashless" },
];
const ADMISSION_TYPE_OPTIONS: { value: Claim["admission_type"]; label: string }[] = [
  { value: "planned", label: "Planned" },
  { value: "emergency", label: "Emergency" },
];

function StepClaimDetails({
  policyId,
  memberId,
  onBack,
  onCreated,
}: {
  policyId: string;
  memberId: string;
  onBack: () => void;
  onCreated: (claim: Claim) => void;
}) {
  const [claimType, setClaimType] = useState<Claim["claim_type"]>("reimbursement");
  const [admissionType, setAdmissionType] = useState<Claim["admission_type"]>("emergency");
  const [hospitalName, setHospitalName] = useState("");
  const [admittedOn, setAdmittedOn] = useState("");
  const [dischargedOn, setDischargedOn] = useState("");
  const [claimedAmount, setClaimedAmount] = useState("");
  const [error, setError] = useState<string | null>(null);

  const createClaim = useCreateClaim();

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    createClaim.mutate(
      {
        policy_id: policyId,
        member_id: memberId,
        claim_type: claimType,
        admission_type: admissionType,
        hospital_name: hospitalName,
        admitted_on: admittedOn || null,
        discharged_on: dischargedOn || null,
        claimed_amount: claimedAmount ? Math.round(Number.parseFloat(claimedAmount) * 100) : null,
      },
      {
        onSuccess: onCreated,
        onError: (err) => setError(err instanceof Error ? err.message : "Couldn't file this claim. Try again."),
      },
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <fieldset className="flex flex-col gap-2">
        <legend className="font-serif text-lg font-semibold text-foreground">Claim type</legend>
        <div className="flex gap-2">
          {CLAIM_TYPE_OPTIONS.map((opt) => (
            <label
              key={opt.value}
              className={`flex-1 cursor-pointer rounded border px-3 py-2 text-center text-sm ${
                claimType === opt.value ? "border-stamp bg-positive-bg text-stamp" : "border-rule text-foreground"
              }`}
            >
              <input type="radio" name="claim_type" className="sr-only" checked={claimType === opt.value} onChange={() => setClaimType(opt.value)} />
              {opt.label}
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset className="flex flex-col gap-2">
        <legend className="font-serif text-lg font-semibold text-foreground">Admission type</legend>
        <div className="flex gap-2">
          {ADMISSION_TYPE_OPTIONS.map((opt) => (
            <label
              key={opt.value}
              className={`flex-1 cursor-pointer rounded border px-3 py-2 text-center text-sm ${
                admissionType === opt.value ? "border-stamp bg-positive-bg text-stamp" : "border-rule text-foreground"
              }`}
            >
              <input
                type="radio"
                name="admission_type"
                className="sr-only"
                checked={admissionType === opt.value}
                onChange={() => setAdmissionType(opt.value)}
              />
              {opt.label}
            </label>
          ))}
        </div>
      </fieldset>

      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-foreground">Hospital name</span>
        <input
          value={hospitalName}
          onChange={(e) => setHospitalName(e.target.value)}
          required
          className="rounded border border-rule bg-background px-2 py-1.5 text-sm"
        />
      </label>

      <div className="grid grid-cols-2 gap-3">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">Admitted on</span>
          <input
            type="date"
            value={admittedOn}
            onChange={(e) => setAdmittedOn(e.target.value)}
            className="rounded border border-rule bg-background px-2 py-1.5 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">Discharged on</span>
          <input
            type="date"
            value={dischargedOn}
            onChange={(e) => setDischargedOn(e.target.value)}
            className="rounded border border-rule bg-background px-2 py-1.5 text-sm"
          />
        </label>
      </div>

      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-foreground">Claimed amount (in rupees)</span>
        <input
          type="number"
          min="0"
          value={claimedAmount}
          onChange={(e) => setClaimedAmount(e.target.value)}
          className="rounded border border-rule bg-background px-2 py-1.5 text-sm"
        />
      </label>

      {error && <p className="text-sm text-flag">{error}</p>}

      <div className="flex gap-2">
        <button type="button" onClick={onBack} className="rounded border border-rule px-4 py-2 text-sm font-medium text-foreground hover:bg-secondary">
          Back
        </button>
        <button
          type="submit"
          disabled={!hospitalName.trim() || createClaim.isPending}
          className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/85 disabled:opacity-50"
        >
          {createClaim.isPending ? "Filing…" : "Next"}
        </button>
      </div>
    </form>
  );
}

// --- Step 3: documents + live completeness ---

function ConnectedDocumentRow({ document, onView, onChanged }: { document: StoredDocument; onView: () => void; onChanged: () => void }) {
  const correctType = useCorrectDocumentType(document.id);
  const deleteDocument = useDeleteDocument();

  return (
    <DocumentRow
      document={document}
      pending={correctType.isPending || deleteDocument.isPending}
      onTypeChange={(t) => correctType.mutate(t, { onSuccess: onChanged })}
      onView={onView}
      onDelete={() => {
        if (window.confirm(`Remove ${document.file_name}? You can re-upload it later if needed.`)) {
          deleteDocument.mutate(document.id, { onSuccess: onChanged });
        }
      }}
    />
  );
}

/** Renders nothing — its only job is to keep polling GET /jobs/{id} until the parse_document job resolves, which is what actually flips the document's parse_status server-side (D-07). The document list itself is what the UI renders; this just drives it forward. */
function ParseJobPoller({ jobId }: { jobId: string }) {
  useJobPolling(jobId, parseDocumentResultSchema);
  return null;
}

function StepDocuments({ claimId, onNext }: { claimId: string; onNext: () => void }) {
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [viewerProvenance, setViewerProvenance] = useState<Provenance | null>(null);
  const [pendingJobIds, setPendingJobIds] = useState<string[]>([]);

  const claimDocs = useClaimDocuments(claimId);
  const completeness = useCompleteness(claimId, { poll: true });
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
      <h2 className="font-serif text-lg font-semibold text-foreground">Upload your documents</h2>
      <p className="text-sm text-muted-foreground">
        Each file's detected type appears in the dropdown next to it — correct it if it's wrong. The panel below updates as documents land.
      </p>

      {completeness.isSuccess && completeness.data && <CompletenessPanel report={completeness.data} />}

      {claimDocs.isPending && <Skeleton className="h-24 w-full" />}
      {claimDocs.isError && (
        <ErrorState message="We couldn't load this claim's documents. Check your connection and try again." onRetry={() => claimDocs.refetch()} />
      )}
      {claimDocs.isSuccess && claimDocs.data.length > 0 && (
        <div className="flex flex-col gap-2">
          {claimDocs.data.map((doc) => (
            <ConnectedDocumentRow
              key={doc.id}
              document={doc}
              onView={() => setViewerProvenance({ document_id: doc.id, page: 1, bbox: null, snippet: null })}
              onChanged={() => void completeness.refetch()}
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

      <Modal open={viewerProvenance !== null} onClose={() => setViewerProvenance(null)} title="Document preview">
        <DocumentViewer fileUrl={MOCK_SOURCE_PDF} activeProvenance={viewerProvenance} />
      </Modal>

      <div className="flex justify-end">
        <button type="button" onClick={onNext} className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/85">
          Next
        </button>
      </div>
    </div>
  );
}

// --- Step 4: bill validation (read-only) ---

function StepBillReview({ claimId, onNext, onBack }: { claimId: string; onNext: () => void; onBack: () => void }) {
  const claimDocs = useClaimDocuments(claimId);
  const hasParsedBill = (claimDocs.data ?? []).some((d) => d.detected_type.value === "itemised_bill" && d.parse_status === "parsed");
  const billValidation = useBillValidation(hasParsedBill ? claimId : null);

  return (
    <div className="flex flex-col gap-4">
      <h2 className="font-serif text-lg font-semibold text-foreground">Bill review</h2>

      {!hasParsedBill && (
        <p className="rounded border border-dashed border-rule px-4 py-6 text-center text-sm text-muted-foreground">
          No itemised bill uploaded yet — this step fills in once one is. Full line-item review with source highlighting lands in a later phase.
        </p>
      )}

      {hasParsedBill && billValidation.isPending && <Skeleton className="h-32 w-full" />}
      {hasParsedBill && billValidation.isError && (
        <ErrorState message="We couldn't validate this bill. Check your connection and try again." onRetry={() => billValidation.refetch()} />
      )}
      {hasParsedBill && billValidation.isSuccess && (
        <div className="flex flex-col gap-3 rounded border border-rule bg-card px-4 py-3">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Total billed</span>
            <Money value={billValidation.data.total_billed} />
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Amount at risk</span>
            <Money value={billValidation.data.total_at_risk} className={billValidation.data.total_at_risk > 0 ? "text-flag" : ""} />
          </div>
          {billValidation.data.flags.length > 0 && (
            <ul className="flex flex-col gap-1.5 border-t border-rule pt-2">
              {billValidation.data.flags.map((flag, i) => (
                <li
                  key={i}
                  className={`text-sm ${flag.severity === "error" ? "text-flag" : flag.severity === "warning" ? "text-caution" : "text-neutral"}`}
                >
                  {flag.message}
                  {flag.estimated_impact != null && (
                    <>
                      {" — "}
                      <Money value={flag.estimated_impact} className="text-inherit" />
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
          <p className="text-xs text-muted-foreground">Full line-item review with source highlighting lands in a later phase.</p>
        </div>
      )}

      <div className="flex justify-between">
        <button type="button" onClick={onBack} className="rounded border border-rule px-4 py-2 text-sm font-medium text-foreground hover:bg-secondary">
          Back
        </button>
        <button type="button" onClick={onNext} className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/85">
          Next
        </button>
      </div>
    </div>
  );
}

// --- Step 5: eligibility (read-only) ---

function StepEligibility({
  claimId,
  onNext,
  onBack,
  onGoToDocuments,
}: {
  claimId: string;
  onNext: () => void;
  onBack: () => void;
  onGoToDocuments: () => void;
}) {
  const [viewerProvenance, setViewerProvenance] = useState<Provenance | null>(null);
  const eligibility = useEligibility(claimId);

  return (
    <div className="flex flex-col gap-4">
      <h2 className="font-serif text-lg font-semibold text-foreground">Eligibility assessment</h2>
      <p className="text-xs text-muted-foreground">An assessment based on your documents — not a guarantee of the outcome.</p>

      {eligibility.isPending && <Skeleton className="h-40 w-full" />}
      {eligibility.isError && (
        <ErrorState message="We couldn't assess this claim. Check your connection and try again." onRetry={() => eligibility.refetch()} />
      )}
      {eligibility.isSuccess && (
        <EligibilityAssessmentView assessment={eligibility.data} onOpenProvenance={setViewerProvenance} onUploadResolvingDocument={onGoToDocuments} />
      )}

      <Modal open={viewerProvenance !== null} onClose={() => setViewerProvenance(null)} title="Governing clause">
        <DocumentViewer fileUrl={MOCK_SOURCE_PDF} activeProvenance={viewerProvenance} />
      </Modal>

      <div className="flex justify-between">
        <button type="button" onClick={onBack} className="rounded border border-rule px-4 py-2 text-sm font-medium text-foreground hover:bg-secondary">
          Back
        </button>
        <button type="button" onClick={onNext} className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/85">
          Next
        </button>
      </div>
    </div>
  );
}

// --- Step 6: summary and file ---

function StepSummary({ claim, onBack }: { claim: Claim; onBack: () => void }) {
  const navigate = useNavigate();
  const policy = usePolicy(claim.policy_id);
  const members = useMembers();
  const completeness = useCompleteness(claim.id);
  const appendEvent = useAppendClaimEvent(claim.id);
  const [error, setError] = useState<string | null>(null);

  const member = (members.data ?? []).find((m) => m.id === claim.member_id) ?? null;
  const canFile = claim.current_state === "intimated";

  function handleFile() {
    setError(null);
    appendEvent.mutate(
      { to_state: "documents_submitted", occurred_at: nowIsoIst(), note: "Documents submitted via claim wizard" },
      {
        onSuccess: () => navigate(`/claims/${claim.id}`),
        onError: (err) => setError(err instanceof Error ? err.message : "Couldn't file this claim. Try again."),
      },
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <h2 className="font-serif text-lg font-semibold text-foreground">Summary</h2>

      <dl className="flex flex-col gap-2 rounded border border-rule bg-card px-4 py-3 text-sm">
        <div className="flex justify-between gap-2">
          <dt className="text-muted-foreground">Policy</dt>
          <dd className="text-right text-foreground">{policy.data ? `${insurerLabel(policy.data)} — ${productLabel(policy.data)}` : "—"}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted-foreground">Member</dt>
          <dd className="text-foreground">{member?.full_name ?? "—"}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted-foreground">Hospital</dt>
          <dd className="text-foreground">{claim.hospital_name}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted-foreground">Claimed amount</dt>
          <dd>
            <Money value={claim.claimed_amount} />
          </dd>
        </div>
      </dl>

      {completeness.isSuccess && completeness.data && <CompletenessPanel report={completeness.data} />}

      {error && <p className="text-sm text-flag">{error}</p>}

      <div className="flex justify-between">
        <button type="button" onClick={onBack} className="rounded border border-rule px-4 py-2 text-sm font-medium text-foreground hover:bg-secondary">
          Back
        </button>
        {canFile ? (
          <button
            type="button"
            onClick={handleFile}
            disabled={appendEvent.isPending}
            className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/85 disabled:opacity-50"
          >
            {appendEvent.isPending ? "Filing…" : "File this claim"}
          </button>
        ) : (
          <button
            type="button"
            onClick={() => navigate(`/claims/${claim.id}`)}
            className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/85"
          >
            This claim is already filed — view it
          </button>
        )}
      </div>
    </div>
  );
}
