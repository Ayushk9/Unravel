import { HttpResponse } from "msw";
import type { ApiErrorBody } from "@/api/types";

/** D-09: every handler asserts the bearer header exists. */
export function requireAuth(request: Request): Response | null {
  const header = request.headers.get("Authorization");
  if (!header?.startsWith("Bearer ")) {
    return errorResponse(401, { code: "unauthorized", message: "Missing bearer token.", retryable: false });
  }
  return null;
}

let requestCounter = 0;
export function nextRequestId(): string {
  requestCounter += 1;
  return `mock-req-${Date.now().toString(36)}-${requestCounter}`;
}

export function genId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

interface ErrorInput {
  code: string;
  message: string;
  field_errors?: ApiErrorBody["error"]["field_errors"];
  retryable?: boolean;
  request_id?: string;
}

/** D-03: the one error envelope shape, for every non-2xx response. */
export function errorResponse(status: number, input: ErrorInput): Response {
  const body: ApiErrorBody = {
    error: {
      code: input.code,
      message: input.message,
      field_errors: input.field_errors ?? [],
      request_id: input.request_id ?? nextRequestId(),
      retryable: input.retryable ?? false,
    },
  };
  return HttpResponse.json(body, { status });
}

export function notFound(message = "Not found."): Response {
  return errorResponse(404, { code: "not_found", message, retryable: false });
}

/** D-04: 409 for illegal claim-state transitions, allowed targets riding in field_errors. */
export function illegalTransition(allowedTargets: string[]): Response {
  return errorResponse(409, {
    code: "illegal_transition",
    message: "That transition isn't allowed from the claim's current state.",
    field_errors: allowedTargets.map((state) => ({ field: "to_state", message: state })),
    retryable: false,
  });
}

/** D-03: collections always come back as { items, next_cursor, total }. */
export function paginate<T>(items: T[], cursor: string | null, limit: number) {
  const startIndex = cursor ? Number.parseInt(cursor, 10) : 0;
  const page = items.slice(startIndex, startIndex + limit);
  const nextIndex = startIndex + limit;
  return {
    items: page,
    next_cursor: nextIndex < items.length ? String(nextIndex) : null,
    total: items.length,
  };
}

function randomBetween(min: number, max: number): number {
  return min + Math.random() * (max - min);
}

/** Simulated latency jitter — the requirement is realistic *timing*, not deterministic data, so randomness here is intended. */
export function delay(minMs: number, maxMs?: number): Promise<void> {
  const ms = maxMs ? randomBetween(minMs, maxMs) : minMs;
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function plainReadDelay(): Promise<void> {
  return delay(150, 400);
}
