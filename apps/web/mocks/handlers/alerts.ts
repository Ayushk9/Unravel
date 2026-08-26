import { http, HttpResponse } from "msw";
import * as db from "../db";
import { plainReadDelay, requireAuth } from "../utils";
import { applyGlobalScenarios, getScenarios } from "../scenarios";

export const alertsHandlers = [
  http.get("*/api/v1/alerts", async ({ request }) => {
    const authError = requireAuth(request);
    if (authError) return authError;
    const scenario = await applyGlobalScenarios();
    if (scenario.shortCircuit) return scenario.shortCircuit;
    await plainReadDelay();

    const list = getScenarios().forceEmpty ? [] : db.listAlerts();
    return HttpResponse.json(list);
  }),
];
