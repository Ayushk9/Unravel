import { http, HttpResponse } from "msw";
import * as db from "../db";
import { paginate, plainReadDelay, requireAuth } from "../utils";
import { applyGlobalScenarios, getScenarios } from "../scenarios";

export const ombudsmanHandlers = [
  http.get("*/api/v1/ombudsman-awards", async ({ request }) => {
    const authError = requireAuth(request);
    if (authError) return authError;
    const scenario = await applyGlobalScenarios();
    if (scenario.shortCircuit) return scenario.shortCircuit;
    await plainReadDelay();

    const url = new URL(request.url);
    const cursor = url.searchParams.get("cursor");
    const limit = Number.parseInt(url.searchParams.get("limit") ?? "20", 10);
    const items = getScenarios().forceEmpty ? [] : db.listOmbudsmanAwards();
    return HttpResponse.json(paginate(items, cursor, limit));
  }),
];
