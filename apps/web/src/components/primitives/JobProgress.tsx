import { Check, FileText, Loader2 } from "lucide-react";

export type UploadStage = "uploading" | "parsing" | "review";

const STAGES: { key: UploadStage; label: string }[] = [
  { key: "uploading", label: "Uploading" },
  { key: "parsing", label: "Parsing" },
  { key: "review", label: "Review" },
];

const STEP_LABEL: Record<string, string> = {
  // Real backend, parse_document job (API_DECISIONS D-28).
  uploading: "Uploading",
  parsing_layout: "Reading the document",
  extracting_fields: "Extracting coverage terms",
  storing: "Saving",
  // Mock handlers.
  classifying_pages: "Classifying pages",
  extracting_tables: "Extracting tables",
  structuring_coverage_profile: "Structuring coverage profile",
  done: "Done",
};

export interface JobProgressProps {
  stage: UploadStage;
  fileName?: string | null;
  pageCount?: number | null;
  progressStep?: string | null;
  progressPercent?: number | null;
  stillWorking?: boolean;
  className?: string;
}

/** The three-stage indicator for /policies/upload — Uploading -> Parsing -> Review, driven by real job polling. */
export function JobProgress({
  stage,
  fileName,
  pageCount,
  progressStep,
  progressPercent,
  stillWorking = false,
  className,
}: JobProgressProps) {
  const stageIndex = STAGES.findIndex((s) => s.key === stage);

  return (
    <div className={`flex flex-col gap-4 ${className ?? ""}`}>
      <ol className="flex items-center gap-2">
        {STAGES.map((s, i) => {
          const done = i < stageIndex;
          const active = i === stageIndex;
          return (
            <li key={s.key} className="flex flex-1 items-center gap-2">
              <span
                className={`flex size-6 shrink-0 items-center justify-center rounded-full border-2 text-xs font-semibold ${
                  done
                    ? "border-stamp bg-stamp text-primary-foreground"
                    : active
                      ? "border-stamp text-stamp"
                      : "border-rule text-muted-foreground"
                }`}
              >
                {done ? <Check className="size-3.5" aria-hidden="true" /> : i + 1}
              </span>
              <span className={`text-sm ${active ? "font-semibold text-foreground" : "text-muted-foreground"}`}>{s.label}</span>
              {i < STAGES.length - 1 && <span className="h-px flex-1 bg-rule" aria-hidden="true" />}
            </li>
          );
        })}
      </ol>

      {stage === "parsing" && (
        <div className="flex flex-col gap-2 rounded border border-rule bg-card px-4 py-3">
          <div className="flex items-center gap-2">
            <FileText className="size-4 shrink-0 text-ink-muted" aria-hidden="true" />
            <span className="text-sm text-foreground">{fileName ?? "Your document"}</span>
            {pageCount != null && <span className="text-xs text-muted-foreground">· {pageCount} pages</span>}
          </div>

          {stillWorking ? (
            <p className="text-sm text-caution">
              Still working — this is taking longer than usual. You can leave this page and come back; we'll pick up where we left off.
            </p>
          ) : (
            <>
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="size-3.5 shrink-0 animate-spin motion-reduce:animate-none" aria-hidden="true" />
                {progressStep ? (STEP_LABEL[progressStep] ?? progressStep) : "Starting…"}
              </div>
              <div role="progressbar" aria-valuenow={progressPercent ?? 0} aria-valuemin={0} aria-valuemax={100} className="h-1.5 w-full overflow-hidden rounded-full bg-rule">
                <div className="h-full rounded-full bg-stamp transition-[width]" style={{ width: `${progressPercent ?? 0}%` }} />
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
