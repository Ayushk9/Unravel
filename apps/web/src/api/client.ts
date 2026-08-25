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
 */
import type { z } from "zod";
import type { ApiErrorBody } from "./types";

export const apiMode = import.meta.env.VITE_API_MODE ?? "mock";
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

const VERSIONED_BASE = `${apiMode === "mock" ? "" : API_BASE_URL}/api/v1`;

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
  method?: "GET" | "POST" | "PATCH" | "DELETE";
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

  const response = await fetch(`${VERSIONED_BASE}${path}`, {
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

  return schema ? schema.parse(json) : (json as T);
}
