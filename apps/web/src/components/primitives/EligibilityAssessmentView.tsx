import type { EligibilityAssessment, EligibilityCheck, Provenance } from "@/api/types";
import { AbstentionCard } from "./AbstentionCard";
import { documentTypeLabel } from "./DocumentTypeSelect";
import { EligibilityCheckItem } from "./EligibilityCheckItem";
import { PrecedentCard } from "./PrecedentCard";
import { VerdictBand } from "./VerdictBand";

/**
 * Synthesises the VerdictBand's one-sentence explanation from check *titles*
 * and counts only — never from a check's `explanation` text, which is where
 * the server's date arithmetic lives. Recomputing or paraphrasing that here
 * would risk two versions disagreeing (binding constraint, brief §Timeline).
 */
function summarizeEligibility(assessment: EligibilityAssessment): string {
  const { band, checks } = assessment;

  if (band === "insufficient_information") {
    return "We're missing information needed to assess this claim — see below.";
  }
  if (band === "likely_eligible") {
    return checks.length > 0
      ? `All ${checks.length} check${checks.length === 1 ? "" : "s"} we could run on this claim came back satisfied.`
      : "We don't have enough checks configured yet to assess this claim.";
  }
  if (band === "at_risk") {
    const atRisk = checks.find((c) => c.status === "at_risk");
    return atRisk ? `This claim is at risk: "${atRisk.title}" needs attention.` : "One or more checks need attention before this claim is filed.";
  }
  const failed = checks.filter((c) => c.status === "failed");
  return failed.length > 0
    ? `${failed.length} check${failed.length === 1 ? "" : "s"} did not pass, most importantly "${failed[0]!.title}."`
    : "This claim did not pass one or more checks.";
}

export interface EligibilityAssessmentViewProps {
  assessment: EligibilityAssessment;
  onOpenProvenance?: (provenance: Provenance) => void;
  onUploadResolvingDocument?: (check: EligibilityCheck) => void;
  className?: string;
}

/**
 * Feature 2's full eligibility surface — verdict band, checks list (ordered
 * failed -> at_risk -> unknown -> satisfied by the server), and the
 * Ombudsman precedent panel. Shared by the claim wizard's read-only step 5
 * and the claim workspace's Eligibility tab so the two can never drift.
 *
 * When the band is insufficient_information, the missing-fact cards take
 * priority — the checks list drops into a collapsed, secondary <details>
 * rather than leading the screen (binding constraint, brief §Eligibility tab).
 */
export function EligibilityAssessmentView({
  assessment,
  onOpenProvenance,
  onUploadResolvingDocument,
  className,
}: EligibilityAssessmentViewProps) {
  const { band, checks, ombudsman_precedent } = assessment;
  const unknownChecks = checks.filter((c) => c.status === "unknown");

  return (
    <div className={`flex flex-col gap-6 ${className ?? ""}`}>
      <VerdictBand band={band} explanation={summarizeEligibility(assessment)} />

      {band === "insufficient_information" ? (
        <div className="flex flex-col gap-4">
          <section className="flex flex-col gap-2">
            <h2 className="font-serif text-lg font-semibold text-foreground">What's missing</h2>
            <div className="flex flex-col gap-2">
              {unknownChecks.length > 0 ? (
                unknownChecks.map((check) => (
                  <AbstentionCard
                    key={check.id}
                    missingFact={check.missing_fact ?? check.explanation}
                    resolvingDocument={check.resolving_document ? documentTypeLabel[check.resolving_document] : null}
                    action={
                      check.resolving_document && onUploadResolvingDocument
                        ? { label: `Upload ${documentTypeLabel[check.resolving_document]}`, onClick: () => onUploadResolvingDocument(check) }
                        : undefined
                    }
                  />
                ))
              ) : (
                <AbstentionCard missingFact="We don't have enough information to assess this claim yet." />
              )}
            </div>
          </section>

          {checks.length > 0 && (
            <details className="rounded border border-rule bg-card px-4 py-3">
              <summary className="cursor-pointer text-sm font-medium text-muted-foreground">Checks we could run ({checks.length})</summary>
              <div className="mt-3 flex flex-col gap-2">
                {checks.map((check) => (
                  <EligibilityCheckItem
                    key={check.id}
                    check={check}
                    onOpenProvenance={onOpenProvenance}
                    onUploadResolvingDocument={onUploadResolvingDocument}
                  />
                ))}
              </div>
            </details>
          )}
        </div>
      ) : (
        <section className="flex flex-col gap-2">
          <h2 className="font-serif text-lg font-semibold text-foreground">Checks</h2>
          <div className="flex flex-col gap-2">
            {checks.map((check) => (
              <EligibilityCheckItem
                key={check.id}
                check={check}
                onOpenProvenance={onOpenProvenance}
                onUploadResolvingDocument={onUploadResolvingDocument}
                defaultExpanded={check.status === "failed"}
              />
            ))}
          </div>
        </section>
      )}

      <section className="flex flex-col gap-2 border-t border-rule pt-4">
        <h2 className="font-serif text-lg font-semibold text-foreground">Cases with a similar denial ground</h2>
        <p className="text-xs text-muted-foreground">
          Past Ombudsman decisions on similar denial grounds — not a prediction of how your claim will be decided.
        </p>
        {ombudsman_precedent.length > 0 ? (
          <div className="flex flex-col gap-2">
            {ombudsman_precedent.map((award) => (
              <PrecedentCard key={award.id} award={award} />
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No similar Ombudsman cases found for this claim yet.</p>
        )}
      </section>
    </div>
  );
}
