import { useEffect, useState } from "react";
import { AlertTriangle, Wrench, X } from "lucide-react";
import type { EligibilityAssessment } from "@/api/types";
import { getScenarios, resetScenarios, setScenarios, subscribeScenarios, type ScenarioState } from "./scenarios";
import { clearValidationIssues, getValidationIssues, subscribeValidationIssues, type ValidationIssue } from "./validationIssues";

/**
 * Dev-build only (brief §8.3). Forces states without editing code or
 * fixtures — every handler in mocks/ reads this same state via
 * mocks/scenarios.ts. Every screen must be reachable in every state it can
 * occupy through this panel, so treat it as a real feature, not a debug
 * afterthought.
 */
const BAND_OPTIONS: { value: EligibilityAssessment["band"] | ""; label: string }[] = [
  { value: "", label: "Not forced" },
  { value: "likely_eligible", label: "Likely eligible" },
  { value: "at_risk", label: "At risk" },
  { value: "likely_ineligible", label: "Likely ineligible" },
  { value: "insufficient_information", label: "Insufficient information" },
];

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center justify-between gap-3 py-1 text-sm">
      <span>{label}</span>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="size-4 accent-stamp"
      />
    </label>
  );
}

function ValidationIssuesSection({ issues }: { issues: ValidationIssue[] }) {
  if (issues.length === 0) return null;
  return (
    <div className="mt-2 border-t border-rule pt-2">
      <div className="mb-1 flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-sm font-semibold text-flag">
          <AlertTriangle className="size-3.5" aria-hidden="true" />
          Validation issues ({issues.length})
        </span>
        <button type="button" onClick={() => clearValidationIssues()} className="text-xs text-muted-foreground underline underline-offset-2">
          Clear
        </button>
      </div>
      <p className="mb-1.5 text-xs text-muted-foreground">
        A live response didn't match its schema — the screen still rendered with the unvalidated payload. Full detail in the console.
      </p>
      <ul className="flex max-h-40 flex-col gap-1 overflow-y-auto text-xs">
        {[...issues].reverse().map((issue, i) => (
          <li key={`${issue.at}-${i}`} className="rounded border border-negative-border bg-negative-bg px-2 py-1">
            <span className="font-mono font-medium text-flag">
              {issue.method} {issue.path}
            </span>
            <span className="block text-muted-foreground">
              {issue.issues.length} field{issue.issues.length === 1 ? "" : "s"}: {issue.issues[0]?.message ?? "—"}
              {issue.issues.length > 1 ? ` (+${issue.issues.length - 1} more)` : ""}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function DevToolbarPanel() {
  const [open, setOpen] = useState(false);
  const [scenarios, setLocalScenarios] = useState<ScenarioState>(getScenarios());
  const [validationIssues, setValidationIssues] = useState<ValidationIssue[]>(getValidationIssues());

  useEffect(() => subscribeScenarios(setLocalScenarios), []);
  useEffect(() => subscribeValidationIssues(setValidationIssues), []);

  return (
    <div className="fixed right-4 bottom-4 z-50 font-sans">
      {open ? (
        <div className="w-72 rounded border-2 border-ink bg-card p-3 shadow-lg">
          <div className="mb-2 flex items-center justify-between border-b border-rule pb-2">
            <span className="flex items-center gap-1.5 text-sm font-semibold">
              <Wrench className="size-3.5" aria-hidden="true" />
              Dev toolbar
            </span>
            <button type="button" onClick={() => setOpen(false)} aria-label="Close dev toolbar">
              <X className="size-4" aria-hidden="true" />
            </button>
          </div>

          <div className="flex flex-col divide-y divide-rule">
            <Toggle label="Force loading" checked={scenarios.forceLoading} onChange={(v) => setScenarios({ forceLoading: v })} />
            <Toggle label="Force empty" checked={scenarios.forceEmpty} onChange={(v) => setScenarios({ forceEmpty: v })} />
            <Toggle label="Force error" checked={scenarios.forceError} onChange={(v) => setScenarios({ forceError: v })} />
            <Toggle label="Slow network" checked={scenarios.slowNetwork} onChange={(v) => setScenarios({ slowNetwork: v })} />
            <Toggle
              label="Low-confidence extraction"
              checked={scenarios.forceLowConfidence}
              onChange={(v) => setScenarios({ forceLowConfidence: v })}
            />
            <Toggle label="Force abstention (Q&A)" checked={scenarios.forceAbstention} onChange={(v) => setScenarios({ forceAbstention: v })} />
            <Toggle
              label="Expired deadline"
              checked={scenarios.forceExpiredDeadline}
              onChange={(v) => setScenarios({ forceExpiredDeadline: v })}
            />
            <Toggle
              label="Force illegal transition (409)"
              checked={scenarios.forceIllegalTransition}
              onChange={(v) => setScenarios({ forceIllegalTransition: v })}
            />
          </div>

          <div className="mt-2 border-t border-rule pt-2">
            <label className="flex flex-col gap-1 text-sm">
              <span>Eligibility band</span>
              <select
                value={scenarios.forceEligibilityBand ?? ""}
                onChange={(e) =>
                  setScenarios({ forceEligibilityBand: (e.target.value || null) as EligibilityAssessment["band"] | null })
                }
                className="rounded border border-rule bg-background px-2 py-1 text-sm"
              >
                {BAND_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <ValidationIssuesSection issues={validationIssues} />

          <button
            type="button"
            onClick={() => resetScenarios()}
            className="mt-3 w-full rounded border border-rule py-1.5 text-sm font-medium hover:bg-secondary"
          >
            Reset all
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setOpen(true)}
          aria-label="Open dev toolbar"
          className="relative flex size-10 items-center justify-center rounded-full border-2 border-ink bg-card shadow-lg hover:bg-secondary"
        >
          <Wrench className="size-4" aria-hidden="true" />
          {/* Glanceable without opening the panel — Task 2: "I need to know it happened without the panel seeing a red error screen." */}
          {validationIssues.length > 0 && (
            <span
              aria-label={`${validationIssues.length} live response validation issue${validationIssues.length === 1 ? "" : "s"}`}
              className="absolute -top-1 -right-1 flex size-4 items-center justify-center rounded-full border border-card bg-flag text-[10px] font-bold text-primary-foreground"
            >
              {validationIssues.length > 9 ? "9+" : validationIssues.length}
            </span>
          )}
        </button>
      )}
    </div>
  );
}

export function DevToolbar() {
  if (!import.meta.env.DEV) return null;
  return <DevToolbarPanel />;
}
