import type { Claim, EligibilityAssessment, EligibilityCheck, Policy } from "@/api/types";
import { approxMonthsBetween, formatDMY, nowIso } from "./dateMath";
import { ombudsmanAwardsByDenialGroundKeyword } from "./fixtures";
import { getScenarios } from "./scenarios";

const STATUS_RANK: Record<EligibilityCheck["status"], number> = { failed: 0, at_risk: 1, unknown: 2, satisfied: 3 };

/**
 * Computed live from the claim + its policy's actual coverage profile —
 * deliberately not hand-typed prose, so the date arithmetic in each
 * explanation can't drift from the waiting-period data it describes.
 */
export function computeEligibility(claim: Claim, policy: Policy): EligibilityAssessment {
  const scenarios = getScenarios();
  if (scenarios.forceEligibilityBand) {
    return forcedAssessment(claim, scenarios.forceEligibilityBand);
  }

  const profile = policy.coverage_profile;
  if (!profile) {
    return {
      claim_id: claim.id,
      band: "insufficient_information",
      checks: [
        {
          id: "coverage_profile_missing",
          title: "Policy coverage profile",
          status: "unknown",
          explanation: "This policy hasn't finished parsing yet, so we can't check anything against it.",
          governing_clause: null,
          missing_fact: "Coverage profile",
          resolving_document: "policy_wording",
        },
      ],
      ombudsman_precedent: [],
      generated_at: nowIso(),
    };
  }

  const checks: EligibilityCheck[] = [];

  const ped = profile.waiting_periods.find((w) => w.kind === "pre_existing");
  if (ped) {
    if (!claim.admitted_on) {
      checks.push({
        id: "ped_waiting_period",
        title: "Pre-existing disease waiting period",
        status: "unknown",
        explanation: "We don't know this claim's admission date yet, so we can't check it against the waiting period.",
        governing_clause: ped.months.provenance,
        missing_fact: "Admission date",
        resolving_document: "discharge_summary",
      });
    } else if (ped.months.value == null || !ped.starts_on || !ped.expires_on) {
      checks.push({
        id: "ped_waiting_period",
        title: "Pre-existing disease waiting period",
        status: "unknown",
        explanation: "Your policy's pre-existing disease waiting period wasn't extracted clearly enough to check.",
        governing_clause: ped.months.provenance,
        missing_fact: "Pre-existing disease waiting period length",
        resolving_document: "policy_wording",
      });
    } else {
      // Plain string comparison — correct for zero-padded ISO dates, and
      // sidesteps the Date-parsing timezone pitfalls this arithmetic
      // deliberately avoids (see dateMath.ts).
      const stillInside = claim.admitted_on < ped.expires_on;
      const monthsIn = approxMonthsBetween(ped.starts_on, claim.admitted_on);
      checks.push({
        id: "ped_waiting_period",
        title: "Pre-existing disease waiting period",
        status: stillInside ? "failed" : "satisfied",
        explanation: stillInside
          ? `Your policy's continuous cover began ${formatDMY(ped.starts_on)}. The pre-existing-disease waiting period is ${ped.months.value} months, so it runs to ${formatDMY(ped.expires_on)}. Your admission on ${formatDMY(claim.admitted_on)} falls ${monthsIn} months inside it.`
          : `Your policy's continuous cover began ${formatDMY(ped.starts_on)}. The pre-existing-disease waiting period ran to ${formatDMY(ped.expires_on)}. Your admission on ${formatDMY(claim.admitted_on)} comes after that, so this check is satisfied.`,
        governing_clause: ped.months.provenance,
        missing_fact: null,
        resolving_document: null,
      });
    }
  }

  const initial = profile.waiting_periods.find((w) => w.kind === "initial");
  if (initial && initial.expires_on && claim.admitted_on) {
    const stillInside = claim.admitted_on < initial.expires_on;
    checks.push({
      id: "initial_waiting_period",
      title: "Initial waiting period",
      status: stillInside ? "failed" : "satisfied",
      explanation: stillInside
        ? `Your policy's initial waiting period runs to ${formatDMY(initial.expires_on)}. Your admission on ${formatDMY(claim.admitted_on)} falls inside it.`
        : `Your policy's initial waiting period ended ${formatDMY(initial.expires_on)}, before your admission on ${formatDMY(claim.admitted_on)}.`,
      governing_clause: initial.months.provenance,
      missing_fact: null,
      resolving_document: null,
    });
  }

  if (claim.claimed_amount != null && profile.sum_insured.value != null) {
    const overSumInsured = claim.claimed_amount > profile.sum_insured.value;
    checks.push({
      id: "sum_insured_adequacy",
      title: "Sum insured adequacy",
      status: overSumInsured ? "at_risk" : "satisfied",
      explanation: overSumInsured
        ? "Your claimed amount is above your policy's sum insured, so part of the bill may not be payable."
        : "Your claimed amount is within your policy's sum insured.",
      governing_clause: profile.sum_insured.provenance,
      missing_fact: null,
      resolving_document: null,
    });
  }

  const orderedChecks = [...checks].sort((a, b) => STATUS_RANK[a.status] - STATUS_RANK[b.status]);

  const band: EligibilityAssessment["band"] = checks.some((c) => c.status === "failed")
    ? "likely_ineligible"
    : checks.some((c) => c.status === "unknown")
      ? "insufficient_information"
      : checks.some((c) => c.status === "at_risk")
        ? "at_risk"
        : "likely_eligible";

  const failedPed = checks.find((c) => c.id === "ped_waiting_period" && c.status === "failed");
  const ombudsman_precedent = failedPed ? ombudsmanAwardsByDenialGroundKeyword("pre-existing") : [];

  return { claim_id: claim.id, band, checks: orderedChecks, ombudsman_precedent, generated_at: nowIso() };
}

function forcedAssessment(claim: Claim, band: EligibilityAssessment["band"]): EligibilityAssessment {
  const byBand: Record<EligibilityAssessment["band"], EligibilityCheck[]> = {
    likely_eligible: [
      {
        id: "forced_check",
        title: "All checks (forced from dev toolbar)",
        status: "satisfied",
        explanation: "Forced into the likely_eligible band from the dev toolbar.",
        governing_clause: null,
        missing_fact: null,
        resolving_document: null,
      },
    ],
    at_risk: [
      {
        id: "forced_check",
        title: "Forced check (dev toolbar)",
        status: "at_risk",
        explanation: "Forced into the at_risk band from the dev toolbar.",
        governing_clause: null,
        missing_fact: null,
        resolving_document: null,
      },
    ],
    likely_ineligible: [
      {
        id: "forced_check",
        title: "Forced check (dev toolbar)",
        status: "failed",
        explanation: "Forced into the likely_ineligible band from the dev toolbar.",
        governing_clause: null,
        missing_fact: null,
        resolving_document: null,
      },
    ],
    insufficient_information: [
      {
        id: "forced_check",
        title: "Forced check (dev toolbar)",
        status: "unknown",
        explanation: "Forced into the insufficient_information band from the dev toolbar.",
        governing_clause: null,
        missing_fact: "Forced from the dev toolbar",
        resolving_document: "policy_wording",
      },
    ],
  };

  return { claim_id: claim.id, band, checks: byBand[band], ombudsman_precedent: [], generated_at: nowIso() };
}
