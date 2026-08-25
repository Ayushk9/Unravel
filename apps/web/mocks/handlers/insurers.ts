import { http, HttpResponse } from "msw";
import * as db from "../db";
import { plainReadDelay, requireAuth } from "../utils";
import { applyGlobalScenarios, getScenarios } from "../scenarios";

export const insurersHandlers = [
  http.get("*/api/v1/insurers/benchmarks", async ({ request }) => {
    const authError = requireAuth(request);
    if (authError) return authError;
    const scenario = await applyGlobalScenarios();
    if (scenario.shortCircuit) return scenario.shortCircuit;
    await plainReadDelay();

    const list = getScenarios().forceEmpty ? [] : db.listBenchmarks();
    return HttpResponse.json(list);
  }),
];
