/**
 * Mock-effects layer: reads scenario state from src/dev/scenarios.ts (the
 * dev toolbar's pure state module) and turns it into actual delayed/forced
 * Response behaviour. Handlers import from this file, not from src/dev/
 * directly — keeps MSW/Response concerns out of the toolbar's state module.
 */
export { getScenarios, setScenarios, resetScenarios, subscribeScenarios } from "@/dev/scenarios";
export type { ScenarioState } from "@/dev/scenarios";

import { getScenarios } from "@/dev/scenarios";
import { errorResponse } from "./utils";

/** Every handler calls this first — forced loading/error/slow-network cut across every endpoint. */
export async function applyGlobalScenarios(): Promise<{ shortCircuit: Response | null }> {
  const s = getScenarios();

  if (s.slowNetwork) {
    await new Promise((resolve) => setTimeout(resolve, 4000 + Math.random() * 3000));
  }
  if (s.forceLoading) {
    // Never resolves — the screen sits in its loading state until the toolbar is reset.
    await new Promise(() => {});
  }
  if (s.forceError) {
    return {
      shortCircuit: errorResponse(500, {
        code: "forced_error",
        message: "This error was forced from the dev toolbar.",
        retryable: true,
      }),
    };
  }
  return { shortCircuit: null };
}
