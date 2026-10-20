import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { MessageCircleQuestion } from "lucide-react";
import type { Provenance } from "@/api/types";
import { useDocumentFile } from "@/api/endpoints/documents";
import { usePolicy } from "@/api/endpoints/policies";
import { insurerLabel, policyNumberLabel, productLabel } from "@/lib/policyLabels";
import { PolicyDetailsForm } from "@/components/PolicyDetailsForm";
import {
  DocumentViewer,
  ErrorState,
  ExtractedField,
  Money,
  Skeleton,
  SubLimitsTable,
  WaitingPeriodTimeline,
} from "@/components/primitives";

export function PolicyDetail() {
  const { id } = useParams<{ id: string }>();
  const policy = usePolicy(id ?? null);
  // The uploaded file itself (D-26), so a provenance highlight lands on the real page.
  const sourceFile = useDocumentFile(policy.data?.source_document_id ?? null);
  const sourceFileUrl = sourceFile.data?.url ?? null;
  const [activeProvenance, setActiveProvenance] = useState<Provenance | null>(null);
  const [mobileViewerOpen, setMobileViewerOpen] = useState(false);

  function openProvenance(p: Provenance) {
    setActiveProvenance(p);
    setMobileViewerOpen(true);
  }

  if (policy.isPending) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  if (policy.isError || !policy.data) {
    return <ErrorState message="We couldn't load this policy. Check your connection and try again." onRetry={() => policy.refetch()} />;
  }

  const profile = policy.data.coverage_profile;

  return (
    <div className="flex flex-col gap-6 lg:flex-row">
      <div className="flex min-w-0 flex-1 flex-col gap-6">
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="font-serif text-2xl font-semibold text-foreground">{productLabel(policy.data)}</h1>
            <p className="text-sm text-muted-foreground">
              {insurerLabel(policy.data)} · Policy {policyNumberLabel(policy.data)}
            </p>
          </div>
          <Link
            to={`/policies/${policy.data.id}/ask`}
            className="inline-flex items-center gap-1.5 rounded border border-rule px-3 py-1.5 text-sm font-medium text-foreground hover:bg-secondary"
          >
            <MessageCircleQuestion className="size-4" aria-hidden="true" />
            Ask about this policy
          </Link>
        </header>

        <section className="flex flex-col gap-2">
          <h2 className="font-serif text-lg font-semibold text-foreground">Policy details</h2>
          <PolicyDetailsForm policy={policy.data} />
        </section>

        {!profile ? (
          <p className="rounded border border-dashed border-rule px-4 py-6 text-center text-sm text-muted-foreground">
            This policy is still being parsed — coverage details aren't ready yet.
          </p>
        ) : (
          <>
            <section className="flex flex-col gap-2">
              <h2 className="font-serif text-lg font-semibold text-foreground">Coverage basics</h2>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                <ExtractedField
                  label="Sum insured"
                  valueDisplay={<Money value={profile.sum_insured.value} />}
                  confidence={profile.sum_insured.confidence}
                  userConfirmed={profile.sum_insured.user_confirmed}
                  provenance={profile.sum_insured.provenance}
                  onOpenProvenance={openProvenance}
                />
                <ExtractedField
                  label="Co-pay"
                  valueDisplay={<span className="font-tabular font-mono">{profile.co_pay_percent.value}%</span>}
                  confidence={profile.co_pay_percent.confidence}
                  userConfirmed={profile.co_pay_percent.user_confirmed}
                  provenance={profile.co_pay_percent.provenance}
                  onOpenProvenance={openProvenance}
                />
                <ExtractedField
                  label="Claim intimation deadline"
                  valueDisplay={<span className="font-tabular font-mono">{profile.intimation_deadline_hours.value} hours</span>}
                  confidence={profile.intimation_deadline_hours.confidence}
                  userConfirmed={profile.intimation_deadline_hours.user_confirmed}
                  provenance={profile.intimation_deadline_hours.provenance}
                  onOpenProvenance={openProvenance}
                />
              </div>
            </section>

            <section className="flex flex-col gap-2">
              <h2 className="font-serif text-lg font-semibold text-foreground">Sub-limits</h2>
              <SubLimitsTable subLimits={profile.sub_limits} onOpenProvenance={openProvenance} />
            </section>

            <section className="flex flex-col gap-2">
              <h2 className="font-serif text-lg font-semibold text-foreground">Waiting periods</h2>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {profile.waiting_periods.map((wp, i) => (
                  <WaitingPeriodTimeline key={i} waitingPeriod={wp} />
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
                      onOpenProvenance={openProvenance}
                    />
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </div>

      {/* Desktop: persistent right pane. Mobile: opens as a sheet when a provenance chip is clicked (brief §6.1). */}
      <aside className="hidden w-full shrink-0 lg:block lg:w-96">
        <DocumentViewer fileUrl={profile ? sourceFileUrl : null} activeProvenance={activeProvenance} className="sticky top-4" />
      </aside>

      {mobileViewerOpen && (
        <div className="fixed inset-0 z-40 flex flex-col justify-end bg-ink/40 lg:hidden" onClick={() => setMobileViewerOpen(false)}>
          <div
            role="dialog"
            aria-label="Document source"
            onClick={(e) => e.stopPropagation()}
            className="max-h-[85vh] overflow-y-auto rounded-t-lg border-t-2 border-ink bg-background p-4"
          >
            <button
              type="button"
              onClick={() => setMobileViewerOpen(false)}
              className="mb-2 ml-auto block rounded border border-rule px-2 py-1 text-xs"
            >
              Close
            </button>
            <DocumentViewer fileUrl={sourceFileUrl} activeProvenance={activeProvenance} />
          </div>
        </div>
      )}
    </div>
  );
}
