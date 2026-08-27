/**
 * THE single allowlist for `VITE_API_MODE=hybrid`. Edit this array — and only
 * this array — to add or remove a route that should hit the real backend
 * while everything else stays on MSW. Both `client.ts` (per-request base URL)
 * and `mocks/hybridPassthrough.ts` (MSW passthrough registration) read this
 * same list, so it can never drift into "live for routing, still mocked for
 * real" or vice versa.
 *
 * `pattern` is relative to `/api/v1`, using `:param`-style dynamic segments —
 * the same syntax MSW's own `http.get(...)` path matching understands, so
 * hybridPassthrough.ts can hand these patterns straight to MSW unmodified.
 */
export type HybridHttpMethod = "GET" | "POST" | "PATCH" | "DELETE";

export interface HybridRoute {
  method: HybridHttpMethod;
  pattern: string;
}

export const HYBRID_LIVE_ROUTES: HybridRoute[] = [
  { method: "POST", pattern: "/documents" },
  { method: "GET", pattern: "/jobs/:id" },
  { method: "GET", pattern: "/policies/:id" },
];

function toPathRegex(pattern: string): RegExp {
  const escaped = pattern
    .split("/")
    .map((segment) => (segment.startsWith(":") ? "[^/]+" : segment.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")))
    .join("/");
  return new RegExp(`^${escaped}$`);
}

/** `path` is what callers pass to `apiFetch` — relative, no `/api/v1` prefix, may carry a query string. */
export function isHybridLiveRoute(method: string, path: string): boolean {
  const pathname = path.split("?")[0] ?? path;
  const upperMethod = method.toUpperCase();
  return HYBRID_LIVE_ROUTES.some((route) => route.method === upperMethod && toPathRegex(route.pattern).test(pathname));
}
