import { http, HttpResponse } from "msw";
import type { CityTier, HouseholdUpdateRequest } from "@/api/types";
import * as db from "../db";
import { errorResponse, plainReadDelay, requireAuth } from "../utils";
import { applyGlobalScenarios } from "../scenarios";

const CITY_TIERS: (CityTier | null)[] = ["metro", "tier_2", "other", null];

/** D-40: the caller's household and its city tier. */
export const householdHandlers = [
  http.get("*/api/v1/household", async ({ request }) => {
    const authError = requireAuth(request);
    if (authError) return authError;
    const scenario = await applyGlobalScenarios();
    if (scenario.shortCircuit) return scenario.shortCircuit;
    await plainReadDelay();
    return HttpResponse.json(db.getHousehold());
  }),

  http.patch("*/api/v1/household", async ({ request }) => {
    const authError = requireAuth(request);
    if (authError) return authError;
    await plainReadDelay();

    const body = (await request.json()) as Partial<HouseholdUpdateRequest>;
    if (!("city_tier" in body) || !CITY_TIERS.includes(body.city_tier ?? null)) {
      return errorResponse(422, {
        code: "validation_error",
        message: "That city tier isn't one of the options.",
        field_errors: [{ field: "city_tier", message: "Must be metro, tier_2, other or null." }],
      });
    }
    return HttpResponse.json(db.setCityTier(body.city_tier ?? null));
  }),
];
