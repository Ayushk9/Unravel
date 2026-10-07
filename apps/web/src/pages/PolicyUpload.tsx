import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { parseDocumentResultSchema } from "@/api/schemas";
import { useDocumentFile, useUploadDocument } from "@/api/endpoints/documents";
import { usePolicy, useCorrectPolicyField } from "@/api/endpoints/policies";
import { useJobPolling } from "@/api/endpoints/jobs";
import {
  AbstentionCard,
  DocumentViewer,
  ErrorState,
  ExtractedField,
  FileDropzone,
  JobProgress,
  Money,
  SubLimitsTable,
  WaitingPeriodTimeline,
  type UploadStage,
} from "@/components/primitives";
import type { Provenance } from "@/api/types";

export function PolicyUpload() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const jobId = searchParams.get("job");
  const fileNameParam = searchParams.get("file");

  const [uploadError, setUploadError] = useState<string | null>(null);
  const [activeProvenance, setActiveProvenance] = useState<Provenance | null>(null);
  const uploadMutation = useUploadDocument();

  const jobQuery = useJobPolling(jobId, parseDocumentResultSchema);
  const policyId = jobQuery.data?.status === "succeeded" ? (jobQuery.data.result?.policy_id ?? null) : null;
  const policyQuery = usePolicy(policyId);
  // The uploaded file itself (D-26), so each provenance chip opens the real page.
  const sourceFile = useDocumentFile(policyQuery.data?.source_document_id ?? null);
  const correctField = useCorrectPolicyField(policyId ?? "");

  function handleFileSelected(file: File) {
    setUploadError(null);
    const idempotencyKey = crypto.randomUUID();
    uploadMutation.mutate(
      { file, claimId: null, idempotencyKey },
      {
        onSuccess: (job) => {
          setSearchParams({ job: job.job_id, file: file.name });
        },
        onError: (err) => {
          setUploadError(err instanceof Error ? err.message : "Upload failed. Try again.");
        },
      },
    );
  }

  function reset() {
    setSearchParams({});
    setUploadError(null);
  }

  // --- Stage 1: no job yet — pick a file ---
  if (!jobId) {
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-6">
        <header>
          <h1 className="font-serif text-2xl font-semibold text-foreground">Upload a policy</h1>
          <p className="text-sm text-muted-foreground">We'll extract the coverage terms so you can review them before saving.</p>
        </header>
        <JobProgress stage="uploading" />
        <FileDropzone onFileSelected={handleFileSelected} />
        {uploadMutation.isPending && <p className="text-sm text-muted-foreground">Uploading…</p>}
        {uploadError && <ErrorState message={uploadError} onRetry={() => setUploadError(null)} />}
      </div>
    );
  }

  // --- Stage 2: parsing — poll the job ---
  if (jobQuery.isPending) {
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-6">
        <header>
          <h1 className="font-serif text-2xl font-semibold text-foreground">Upload a policy</h1>
        </header>
        <JobProgress stage="parsing" fileName={fileNameParam} />
      </div>
    );
  }

  if (jobQuery.isError || jobQuery.data?.status === "failed") {
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-6">
        <header>
          <h1 className="font-serif text-2xl font-semibold text-foreground">Upload a policy</h1>
        </header>
        <ErrorState message="We couldn't parse this document. Try uploading it again." onRetry={reset} />
      </div>
    );
  }

  if (jobQuery.data?.status !== "succeeded") {
    const stage: UploadStage = "parsing";
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-6">
        <header>
          <h1 className="font-serif text-2xl font-semibold text-foreground">Upload a policy</h1>
        </header>
        <JobProgress
          stage={stage}
          fileName={fileNameParam}
          progressStep={jobQuery.data?.progress?.step}
          progressPercent={jobQuery.data?.progress?.percent}
          stillWorking={jobQuery.timedOut}
        />
      </div>
    );
  }

  // --- Stage 3: review — job succeeded ---
  if (!policyId) {
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-6">
        <header>
          <h1 className="font-serif text-2xl font-semibold text-foreground">Upload a policy</h1>
        </header>
        <JobProgress stage="review" fileName={fileNameParam} />
        <AbstentionCard
          missingFact="We couldn't extract structured coverage terms from this document."
          resolvingDocument="A clearer scan of your policy schedule, or the full policy wording document"
          action={{ label: "Try a different file", onClick: reset }}
        />
      </div>
    );
  }

  if (policyQuery.isPending) {
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-6">
        <JobProgress stage="review" fileName={fileNameParam} />
        <p className="text-sm text-muted-foreground">Loading extracted terms…</p>
      </div>
    );
  }

  if (policyQuery.isError || !policyQuery.data) {
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-6">
        <ErrorState message="We couldn't load the extracted terms. Try again." onRetry={() => policyQuery.refetch()} />
      </div>
    );
  }

  const profile = policyQuery.data.coverage_profile;
  if (!profile) {
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-6">
        <AbstentionCard
          missingFact="This policy's coverage profile isn't ready yet."
          resolvingDocument="Wait a moment and refresh — parsing may still be finishing."
        />
      </div>
    );
  }

  interface CorrectableField {
    key: string;
    label: string;
    fieldPath: string;
    valueDisplay: React.ReactNode;
    confidence: typeof profile.sum_insured.confidence;
    userConfirmed: boolean;
    provenance: Provenance | null;
    snippet: string | null;
    parse: (raw: string) => string | number;
    placeholder: string;
  }

  const correctableFields: CorrectableField[] = [
    {
      key: "sum_insured",
      label: "Sum insured",
      fieldPath: "sum_insured",
      valueDisplay: <Money value={profile.sum_insured.value} />,
      confidence: profile.sum_insured.confidence,
      userConfirmed: profile.sum_insured.user_confirmed,
      provenance: profile.sum_insured.provenance,
      snippet: profile.sum_insured.provenance?.snippet ?? null,
      parse: (raw) => Math.round(Number.parseFloat(raw) * 100),
      placeholder: "Amount in rupees",
    },
    {
      key: "co_pay_percent",
      label: "Co-pay",
      fieldPath: "co_pay_percent",
      valueDisplay: <span className="font-tabular font-mono">{profile.co_pay_percent.value}%</span>,
      confidence: profile.co_pay_percent.confidence,
      userConfirmed: profile.co_pay_percent.user_confirmed,
      provenance: profile.co_pay_percent.provenance,
      snippet: profile.co_pay_percent.provenance?.snippet ?? null,
      parse: (raw) => Number.parseFloat(raw),
      placeholder: "Percent",
    },
    {
      key: "intimation_deadline_hours",
      label: "Claim intimation deadline",
      fieldPath: "intimation_deadline_hours",
      valueDisplay: <span className="font-tabular font-mono">{profile.intimation_deadline_hours.value} hours</span>,
      confidence: profile.intimation_deadline_hours.confidence,
      userConfirmed: profile.intimation_deadline_hours.user_confirmed,
      provenance: profile.intimation_deadline_hours.provenance,
      snippet: profile.intimation_deadline_hours.provenance?.snippet ?? null,
      parse: (raw) => Number.parseFloat(raw),
      placeholder: "Hours",
    },
    ...profile.sub_limits.map(
      (s): CorrectableField => ({
        key: `sub_limit_${s.category}`,
        label: `${s.label} cap`,
        fieldPath: `sub_limits.${s.category}.cap_amount`,
        valueDisplay: <Money value={s.cap_amount.value} />,
        confidence: s.cap_amount.confidence,
        userConfirmed: s.cap_amount.user_confirmed,
        provenance: s.cap_amount.provenance,
        snippet: s.cap_amount.provenance?.snippet ?? null,
        parse: (raw) => Math.round(Number.parseFloat(raw) * 100),
        placeholder: "Amount in rupees",
      }),
    ),
  ];

  const lowConfidenceFields = correctableFields.filter((f) => f.confidence === "low" && !f.userConfirmed);

  function submitCorrection(field: CorrectableField, rawValue: string | null, confirmOnly: boolean) {
    const value = rawValue === null ? undefined : field.parse(rawValue);
    correctField.mutate(
      { fieldPath: field.fieldPath, value: confirmOnly ? getCurrentRawValue(field) : (value as number), user_confirmed: true },
      { onError: () => setUploadError("Couldn't save that correction. Try again.") },
    );
  }

  function getCurrentRawValue(field: CorrectableField): number {
    // Re-read the live value from profile at call time so "Confirm" (no edit) submits the current value, not a stale closure.
    switch (field.key) {
      case "sum_insured":
        return profile!.sum_insured.value ?? 0;
      case "co_pay_percent":
        return profile!.co_pay_percent.value ?? 0;
      case "intimation_deadline_hours":
        return profile!.intimation_deadline_hours.value ?? 0;
      default: {
        const subLimit = profile!.sub_limits.find((s) => `sub_limit_${s.category}` === field.key);
        return subLimit?.cap_amount.value ?? 0;
      }
    }
  }

  return (
    <div className="flex flex-col gap-6 lg:flex-row">
      <div className="flex min-w-0 flex-1 flex-col gap-6">
        <header>
          <h1 className="font-serif text-2xl font-semibold text-foreground">Review extracted terms</h1>
          <p className="text-sm text-muted-foreground">
            {fileNameParam ?? "Your document"} — check the values below against your policy before saving.
          </p>
        </header>

        <JobProgress stage="review" fileName={fileNameParam} />

        {lowConfidenceFields.length > 0 && (
          <section className="flex flex-col gap-2 rounded border-2 border-caution-border bg-caution-bg p-4">
            <h2 className="font-serif text-lg font-semibold text-caution">
              Confirm these {lowConfidenceFields.length} value{lowConfidenceFields.length === 1 ? "" : "s"}
            </h2>
            <p className="text-sm text-foreground">
              These were extracted with low confidence. Check them against the source page and confirm or correct each one.
            </p>
            <div className="flex flex-col gap-2">
              {lowConfidenceFields.map((field) => (
                <ExtractedField
                  key={field.key}
                  label={field.label}
                  valueDisplay={field.valueDisplay}
                  confidence={field.confidence}
                  userConfirmed={field.userConfirmed}
                  provenance={field.provenance}
                  snippet={field.snippet}
                  onOpenProvenance={setActiveProvenance}
                  pending={correctField.isPending}
                  onConfirm={() => submitCorrection(field, null, true)}
                  onCorrect={(raw) => submitCorrection(field, raw, false)}
                  correctPlaceholder={field.placeholder}
                />
              ))}
            </div>
          </section>
        )}

        <section className="flex flex-col gap-2">
          <h2 className="font-serif text-lg font-semibold text-foreground">Coverage basics</h2>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            {correctableFields.slice(0, 3).map((field) => (
              <ExtractedField
                key={field.key}
                label={field.label}
                valueDisplay={field.valueDisplay}
                confidence={field.confidence}
                userConfirmed={field.userConfirmed}
                provenance={field.provenance}
                onOpenProvenance={setActiveProvenance}
              />
            ))}
          </div>
        </section>

        <section className="flex flex-col gap-2">
          <h2 className="font-serif text-lg font-semibold text-foreground">Sub-limits</h2>
          <SubLimitsTable subLimits={profile.sub_limits} onOpenProvenance={setActiveProvenance} />
        </section>

        <section className="flex flex-col gap-2">
          <h2 className="font-serif text-lg font-semibold text-foreground">Waiting periods</h2>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {profile.waiting_periods.map((wp) => (
              <WaitingPeriodTimeline key={wp.kind} waitingPeriod={wp} />
            ))}
          </div>
        </section>

        {profile.exclusions.length > 0 && (
          <section className="flex flex-col gap-2">
            <h2 className="font-serif text-lg font-semibold text-foreground">Exclusions</h2>
            <div className="flex flex-col gap-2">
              {profile.exclusions.map((exclusion, i) => (
                <ExtractedField
                  key={i}
                  label={`Exclusion ${i + 1}`}
                  valueDisplay={<span className="text-sm">{exclusion.value}</span>}
                  confidence={exclusion.confidence}
                  userConfirmed={exclusion.user_confirmed}
                  provenance={exclusion.provenance}
                  onOpenProvenance={setActiveProvenance}
                />
              ))}
            </div>
          </section>
        )}

        <button
          type="button"
          onClick={() => navigate(`/policies/${policyId}`)}
          className="w-fit rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/85"
        >
          Done — view policy
        </button>
        <p className="text-xs text-muted-foreground">
          This policy is saved. Fields you haven't confirmed keep the unverified treatment wherever they appear.
        </p>
      </div>

      <aside className="w-full shrink-0 lg:w-96">
        <DocumentViewer fileUrl={sourceFile.data?.url ?? null} activeProvenance={activeProvenance} className="sticky top-4" />
      </aside>
    </div>
  );
}
