import { http, HttpResponse } from "msw";

/**
 * Infra endpoint used only to prove the mock/live transport seam works end to
 * end. Not part of a vertical slice in docs/API_DECISIONS.md §7 — real slices
 * add their own handler files alongside this one.
 */
export const healthHandlers = [
  http.get("*/api/v1/health", ({ request }) => {
    if (!request.headers.get("Authorization")) {
      return HttpResponse.json(
        {
          error: {
            code: "unauthorized",
            message: "Missing bearer token.",
            field_errors: [],
            request_id: "mock-request-id",
            retryable: false,
          },
        },
        { status: 401 },
      );
    }

    return HttpResponse.json({ status: "ok" });
  }),
];
