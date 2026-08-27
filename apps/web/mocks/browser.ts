import { setupWorker } from "msw/browser";
import { apiMode } from "@/api/client";
import { handlers } from "./handlers";
import { hybridPassthroughHandlers } from "./hybridPassthrough";

/**
 * Passthrough handlers go FIRST — MSW matches in array order and stops at the
 * first match, so an allowlisted route hits its passthrough() before the real
 * mock handler underneath ever sees it. Only registered in hybrid mode; mock
 * mode behaves exactly as before (this is `[]` there, so `handlers` is
 * untouched — no regression).
 */
export const worker = setupWorker(...(apiMode === "hybrid" ? hybridPassthroughHandlers : []), ...handlers);
