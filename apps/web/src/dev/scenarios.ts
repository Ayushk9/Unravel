/**
 * Pure scenario state — no MSW, no Response objects, no mocks/ imports.
 * This is what makes it safe for DevToolbar.tsx to import directly: CLAUDE.md
 * says components never import from mocks/, and this file lives entirely on
 * the src/ side of that line. mocks/scenarios.ts (the mock-effects layer
 * that actually builds delayed/forced Responses) imports its state FROM
 * here — the dependency only ever runs mocks/ -> src/dev/, never the
 * reverse. See DECISIONS.md.
 */
import type { EligibilityAssessment } from "@/api/types";

export interface ScenarioState {
  forceLoading: boolean;
  forceEmpty: boolean;
  forceError: boolean;
  slowNetwork: boolean;
  forceLowConfidence: boolean;
  forceAbstention: boolean;
  forceEligibilityBand: EligibilityAssessment["band"] | null;
  forceExpiredDeadline: boolean;
}

export const defaultScenarioState: ScenarioState = {
  forceLoading: false,
  forceEmpty: false,
  forceError: false,
  slowNetwork: false,
  forceLowConfidence: false,
  forceAbstention: false,
  forceEligibilityBand: null,
  forceExpiredDeadline: false,
};

let state: ScenarioState = { ...defaultScenarioState };
const subscribers = new Set<(state: ScenarioState) => void>();

export function getScenarios(): ScenarioState {
  return state;
}

export function setScenarios(patch: Partial<ScenarioState>): void {
  state = { ...state, ...patch };
  subscribers.forEach((cb) => cb(state));
}

export function resetScenarios(): void {
  setScenarios(defaultScenarioState);
}

export function subscribeScenarios(cb: (state: ScenarioState) => void): () => void {
  subscribers.add(cb);
  return () => subscribers.delete(cb);
}
