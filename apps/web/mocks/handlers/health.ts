import { http, HttpResponse } from "msw";
import { requireAuth } from "../utils";

/**
 * Infra endpoint used only to prove the mock/live transport seam works end to
 * end. Not part of a vertical slice in docs/API_DECISIONS.md §7 — real slices
 * add their own handler files alongside this one.
 */
export const healthHandlers = [
  http.get("*/api/v1/health", ({ request }) => {
    const authError = requireAuth(request);
    if (authError) return authError;
    return HttpResponse.json({ status: "ok" });
  }),
];
