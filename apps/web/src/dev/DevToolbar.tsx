import { useEffect, useState } from "react";
import { Wrench, X } from "lucide-react";
import type { EligibilityAssessment } from "@/api/types";
import { getScenarios, resetScenarios, setScenarios, subscribeScenarios, type ScenarioState } from "./scenarios";

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

function DevToolbarPanel() {
  const [open, setOpen] = useState(false);
  const [scenarios, setLocalScenarios] = useState<ScenarioState>(getScenarios());

  useEffect(() => subscribeScenarios(setLocalScenarios), []);

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
          className="flex size-10 items-center justify-center rounded-full border-2 border-ink bg-card shadow-lg hover:bg-secondary"
        >
          <Wrench className="size-4" aria-hidden="true" />
        </button>
      )}
    </div>
  );
}

export function DevToolbar() {
  if (!import.meta.env.DEV) return null;
  return <DevToolbarPanel />;
}
