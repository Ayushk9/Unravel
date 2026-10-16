import type { Claim, Confidence, EligibilityAssessment, EligibilityCheck, MissingFact, Policy } from "@/api/types";
import { formatDMY, nowIso } from "./dateMath";
import { ombudsmanAwardsByDenialGroundKeyword } from "./fixtures";
import { getScenarios } from "./scenarios";

/**
 * A small stand-in for Engine B (engines/rules), enough to exercise every
 * screen state in mock mode. The real rules, and their exact wording, live in
 * the backend; this file only mirrors the wire shape (D-36) and the band
 * precedence.
 */

const STATUS_RANK: Record<EligibilityCheck["status"], number> = { failed: 0, at_risk: 1, unknown: 2, satisfied: 3 };
const CRITICAL = new Set(["coverage_profile", "initial_waiting_period", "ped_waiting_period"]);
const PRECEDENT_NOTE = "Precedent corpus not yet loaded, so no similar Ombudsman decisions are shown.";

const ADMISSION_DATE: MissingFact = {
  fact: "Date of admission",
  where_to_get: "On the hospital's discharge summary or admission note.",
  resolving_document: "discharge_summary",
};
const IS_PRE_EXISTING: MissingFact = {
  fact: "Whether this illness started before the policy did (a pre-existing condition)",
  where_to_get: "Your doctor or your own medical history; answer it on this claim.",
  resolving_document: null,
};

interface CheckInput {
  id: string;
  title: string;
  status: EligibilityCheck["status"];
  explanation: string;
  governing_clause: EligibilityCheck["governing_clause"];
  confidence?: Confidence;
  values?: EligibilityCheck["values"];
  missing_facts?: MissingFact[];
}

/** Fills the D-36 fields the way the backend does: missing_fact / resolving_document mirror the first missing fact. */
function check(input: CheckInput): EligibilityCheck {
  const missing = input.missing_facts ?? [];
  return {
    ...input,
    confidence: input.confidence ?? "high",
    values: input.values ?? {},
    missing_facts: missing,
    missing_fact: missing[0]?.fact ?? null,
    resolving_document: missing[0]?.resolving_document ?? null,
  };
}

function bandOf(checks: EligibilityCheck[]): EligibilityAssessment["band"] {
  if (checks.some((c) => c.status === "unknown" && CRITICAL.has(c.id))) return "insufficient_information";
  if (checks.some((c) => c.status === "failed" && c.confidence === "high")) return "likely_ineligible";
  if (checks.some((c) => c.status === "failed" || c.status === "at_risk")) return "at_risk";
  return "likely_eligible";
}

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
        check({
          id: "coverage_profile",
          title: "Policy coverage details",
          status: "unknown",
          confidence: "low",
          explanation: "This policy's coverage details have not been read yet, so nothing can be checked against them.",
          governing_clause: null,
          missing_facts: [{ fact: "Your policy's coverage details", where_to_get: "In your policy wording.", resolving_document: "policy_wording" }],
        }),
      ],
      ombudsman_precedent: [],
      ombudsman_precedent_note: PRECEDENT_NOTE,
      generated_at: nowIso(),
    };
  }

  const checks: EligibilityCheck[] = [];
  const facts = claim.facts;

  const ped = profile.waiting_periods.find((w) => w.kind === "pre_existing");
  if (ped) {
    const base = { id: "ped_waiting_period", title: "Pre-existing disease waiting period", governing_clause: ped.months.provenance };
    if (facts.condition_is_pre_existing === null) {
      checks.push(check({
        ...base,
        status: "unknown",
        explanation: "Whether this waiting period applies depends on facts about the illness that we don't have yet.",
        missing_facts: [IS_PRE_EXISTING],
      }));
    } else if (facts.condition_is_pre_existing === false) {
      checks.push(check({
        ...base,
        status: "satisfied",
        explanation: "You said this illness is not pre-existing. The pre-existing disease waiting period therefore does not apply.",
        values: { condition_is_pre_existing: false },
      }));
    } else if (!claim.admitted_on) {
      checks.push(check({ ...base, status: "unknown", explanation: "We don't know the admission date yet.", missing_facts: [ADMISSION_DATE] }));
    } else if (ped.months.value == null || !ped.starts_on || !ped.expires_on) {
      checks.push(check({
        ...base,
        status: "unknown",
        confidence: "low",
        explanation: "Your policy's pre-existing disease waiting period wasn't extracted clearly enough to check.",
        missing_facts: [{ fact: "Your policy's pre-existing disease waiting period", where_to_get: "In your policy wording.", resolving_document: "policy_wording" }],
      }));
    } else {
      // Plain string comparison is correct for zero-padded ISO dates (see dateMath.ts).
      const stillInside = claim.admitted_on < ped.expires_on;
      checks.push(check({
        ...base,
        status: stillInside ? "failed" : "satisfied",
        explanation: stillInside
          ? `You said this illness is pre-existing. Cover started ${formatDMY(ped.starts_on)}; the ${ped.months.value}-month waiting period ends on ${formatDMY(ped.expires_on)}. Your admission on ${formatDMY(claim.admitted_on)} is before that date.`
          : `You said this illness is pre-existing. Cover started ${formatDMY(ped.starts_on)}; the ${ped.months.value}-month waiting period ended on ${formatDMY(ped.expires_on)}. Your admission on ${formatDMY(claim.admitted_on)} is on or after that date, so the period has been served.`,
        values: { waiting_months: ped.months.value, waiting_period_ends: ped.expires_on, admitted_on: claim.admitted_on },
      }));
    }
  }

  const initial = profile.waiting_periods.find((w) => w.kind === "initial");
  if (initial && initial.expires_on && claim.admitted_on) {
    const stillInside = claim.admitted_on < initial.expires_on;
    checks.push(check({
      id: "initial_waiting_period",
      title: "Initial waiting period",
      status: stillInside ? "failed" : "satisfied",
      explanation: stillInside
        ? `Your policy's initial waiting period runs to ${formatDMY(initial.expires_on)}. Your admission on ${formatDMY(claim.admitted_on)} is before that date.`
        : `Your policy's initial waiting period ended ${formatDMY(initial.expires_on)}, before your admission on ${formatDMY(claim.admitted_on)}.`,
      governing_clause: initial.months.provenance,
      values: { waiting_period_ends: initial.expires_on, admitted_on: claim.admitted_on },
    }));
  }

  if (claim.claimed_amount != null && profile.sum_insured.value != null) {
    const over = claim.claimed_amount > profile.sum_insured.value;
    checks.push(check({
      id: "sum_insured_adequacy",
      title: "Amount within the sum insured",
      status: over ? "at_risk" : "satisfied",
      explanation: over
        ? "The amount claimed is more than your sum insured. The part above the sum insured is not payable under this policy."
        : "The amount claimed is within your sum insured.",
      governing_clause: profile.sum_insured.provenance,
      confidence: profile.sum_insured.user_confirmed ? "high" : profile.sum_insured.confidence,
      values: { claimed_amount: claim.claimed_amount, sum_insured: profile.sum_insured.value },
    }));
  }

  const band = bandOf(checks);
  const ordered = [...checks].sort((a, b) =>
    band === "insufficient_information" ? Number(b.status === "unknown") - Number(a.status === "unknown") : STATUS_RANK[a.status] - STATUS_RANK[b.status],
  );
  const failedPed = checks.some((c) => c.id === "ped_waiting_period" && c.status === "failed");
  const ombudsman_precedent = failedPed ? ombudsmanAwardsByDenialGroundKeyword("pre-existing") : [];

  return {
    claim_id: claim.id,
    band,
    checks: ordered,
    ombudsman_precedent,
    ombudsman_precedent_note: ombudsman_precedent.length > 0 ? null : PRECEDENT_NOTE,
    generated_at: nowIso(),
  };
}

function forcedAssessment(claim: Claim, band: EligibilityAssessment["band"]): EligibilityAssessment {
  const status: Record<EligibilityAssessment["band"], EligibilityCheck["status"]> = {
    likely_eligible: "satisfied",
    at_risk: "at_risk",
    likely_ineligible: "failed",
    insufficient_information: "unknown",
  };
  const forced = check({
    id: "forced_check",
    title: "Forced check (dev toolbar)",
    status: status[band],
    explanation: `Forced into the ${band} band from the dev toolbar.`,
    governing_clause: null,
    missing_facts:
      band === "insufficient_information"
        ? [{ fact: "Forced from the dev toolbar", where_to_get: "Turn the scenario off in the dev toolbar.", resolving_document: "policy_wording" }]
        : [],
  });
  return { claim_id: claim.id, band, checks: [forced], ombudsman_precedent: [], ombudsman_precedent_note: PRECEDENT_NOTE, generated_at: nowIso() };
}
