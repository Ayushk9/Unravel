/**
 * The only file in this codebase that calls fetch(). Components never call fetch
 * and never import from mocks/; they use hooks in src/api/endpoints/*, which call
 * this client. This file is also the only place VITE_API_MODE and
 * VITE_API_BASE_URL are read.
 *
 * Transport rules this implements — see docs/API_DECISIONS.md:
 * D-01 versioned base path, D-02 snake_case untouched, D-03 response envelope
 * and error shape, D-09 bearer auth header on every request, D-10 no
 * household id is ever sent as a parameter.
 *
 * Three modes (CONTRACTS.md documents this for the backend team):
 * - "mock": every request relative, MSW intercepts everything.
 * - "live": every request absolute, against VITE_API_BASE_URL, MSW never starts.
 * - "hybrid": per-request — routes in HYBRID_LIVE_ROUTES go absolute/live,
 *   everything else stays relative/mocked. See hybridRoutes.ts for the
 *   allowlist itself and mocks/hybridPassthrough.ts for how MSW is kept from
 *   shadowing the live routes.
 */
import type { z } from "zod";
import type { ApiErrorBody } from "./types";
import { HYBRID_LIVE_ROUTES, isHybridLiveRoute } from "./hybridRoutes";
import { recordValidationIssue } from "@/dev/validationIssues";

export const apiMode = import.meta.env.VITE_API_MODE ?? "mock";
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

if (import.meta.env.DEV) {
  if (apiMode === "hybrid") {
    const liveList = HYBRID_LIVE_ROUTES.map((r) => `${r.method} ${r.pattern}`).join(", ");
    console.info(`[api] mode: hybrid — live against ${API_BASE_URL} for: ${liveList}`);
  } else {
    console.info(`[api] mode: ${apiMode}${apiMode === "live" ? ` — live against ${API_BASE_URL}` : ""}`);
  }
}

/** Resolved per request, not once at module load — hybrid mode needs to route different paths differently. Also drives Task 2's parse-vs-safeParse split below: "live" means this specific response came from the real backend, not a fixture. */
function isRouteLive(method: string, path: string): boolean {
  return apiMode === "live" || (apiMode === "hybrid" && isHybridLiveRoute(method, path));
}

function resolveBaseUrl(isLive: boolean): string {
  return `${isLive ? API_BASE_URL : ""}/api/v1`;
}

// Real auth arrives with Supabase in a later phase. A stubbed token is sent from
// day one (D-09) so no endpoint is ever built assuming the header is optional.
const STUB_TOKEN = "mock-household-token";

export class ApiError extends Error {
  code: string;
  fieldErrors: ApiErrorBody["error"]["field_errors"];
  requestId: string;
  retryable: boolean;
  status: number;

  constructor(status: number, body: ApiErrorBody) {
    super(body.error.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.error.code;
    this.fieldErrors = body.error.field_errors;
    this.requestId = body.error.request_id;
    this.retryable = body.error.retryable;
  }
}

export interface RequestOptions<T> {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  headers?: Record<string, string>;
  idempotencyKey?: string;
  signal?: AbortSignal;
  /** Parses the response body at the client boundary (D-06's enum .catch() lives here). Omit only for endpoints that don't return a body (204s). */
  schema?: z.ZodType<T>;
}

export async function apiFetch<T = unknown>(path: string, options: RequestOptions<T> = {}): Promise<T> {
  const { method = "GET", body, headers, idempotencyKey, signal, schema } = options;
  const isFormData = body instanceof FormData;
  const isLive = isRouteLive(method, path);

  const response = await fetch(`${resolveBaseUrl(isLive)}${path}`, {
    method,
    signal,
    headers: {
      Authorization: `Bearer ${STUB_TOKEN}`,
      ...(body && !isFormData ? { "Content-Type": "application/json" } : {}),
      ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}),
      ...headers,
    },
    body: isFormData ? body : body ? JSON.stringify(body) : undefined,
  });

  if (response.status === 204) {
    return undefined as T;
  }

  const json = (await response.json()) as unknown;

  if (!response.ok) {
    throw new ApiError(response.status, json as ApiErrorBody);
  }

  if (!schema) {
    return json as T;
  }

  // Task 2: our zod schemas were written against hand-authored fixtures, and
  // real extraction output will differ in ways the fixtures never exercised.
  // A throwing .parse() inside a TanStack Query queryFn takes the whole
  // screen out, and reads as a backend failure when it's actually schema
  // drift on our side. On the mock path this stays `parse` (throws) on
  // purpose — fixture drift is our bug and should fail loudly in dev. On the
  // live path, degrade instead: log loudly (dev only), record it for the dev
  // toolbar's indicator, and hand back the unvalidated payload so the screen
  // still renders. Schemas are never loosened to make real data fit — a
  // schema believed wrong gets logged in DECISIONS.md, not patched here.
  if (!isLive) {
    return schema.parse(json);
  }

  const result = schema.safeParse(json);
  if (result.success) {
    return result.data;
  }

  if (import.meta.env.DEV) {
    console.error(`[api] live response failed schema validation: ${method} ${path}`, result.error.issues);
    console.error("[api] raw response body:", json);
  }
  recordValidationIssue({
    method,
    path,
    issues: result.error.issues.map((issue) => ({ path: issue.path as (string | number)[], message: issue.message })),
  });
  return json as T;
}
