/**
 * Hybrid-mode-only MSW handlers. Every existing mock handler in handlers/ uses
 * an origin-agnostic wildcard-host pattern (a leading "*" followed by
 * "/api/v1/...") — that wildcard matches ANY origin, including a real
 * backend's absolute URL. Which means simply pointing client.ts at a live
 * host for an allowlisted route is not enough on its own: the matching mock
 * handler underneath would still answer it, silently, and the panel would be
 * looking at fixture data believing it's live. That's exactly the failure
 * this file exists to prevent.
 *
 * These handlers are built from the SAME allowlist client.ts routes against
 * (hybridRoutes.ts) and registered FIRST in the worker's handler list
 * (browser.ts) — MSW matches in array order and stops at the first match, so
 * an allowlisted request hits one of these, calls passthrough(), and MSW lets
 * it continue to the real network untouched. The real mock handler for that
 * same path never gets a turn.
 */
import { http, passthrough } from "msw";
import { HYBRID_LIVE_ROUTES, type HybridHttpMethod } from "@/api/hybridRoutes";

const methodFn: Record<HybridHttpMethod, typeof http.get> = {
  GET: http.get,
  POST: http.post,
  PATCH: http.patch,
  DELETE: http.delete,
};

export const hybridPassthroughHandlers = HYBRID_LIVE_ROUTES.map((route) =>
  methodFn[route.method](`*/api/v1${route.pattern}`, ({ request }) => {
    if (import.meta.env.DEV) {
      console.info(`[api] hybrid passthrough — not mocked, going live: ${request.method} ${request.url}`);
    }
    return passthrough();
  }),
);
