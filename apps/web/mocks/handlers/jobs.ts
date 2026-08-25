import { http, HttpResponse } from "msw";
import * as db from "../db";
import { requireAuth, notFound } from "../utils";

export const jobsHandlers = [
  http.get("*/api/v1/jobs/:jobId", ({ request, params }) => {
    const authError = requireAuth(request);
    if (authError) return authError;

    const job = db.getJob(params.jobId as string);
    if (!job) return notFound("No job with that id.");
    return HttpResponse.json(job);
  }),
];
