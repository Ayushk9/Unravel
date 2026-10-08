import { CheckCircle2, CircleDashed } from "lucide-react";
import type { CompletenessReport } from "@/api/types";
import { documentTypeLabel } from "./DocumentTypeSelect";

export interface CompletenessPanelProps {
  report: CompletenessReport;
  className?: string;
}

/** Feature 4 — live view of POST /claims/{id}/completeness. Updates as documents land and get classified. */
export function CompletenessPanel({ report, className }: CompletenessPanelProps) {
  const allPresent = report.missing.length === 0;

  return (
    <div
      className={`flex flex-col gap-2 rounded border px-4 py-3 ${
        allPresent ? "border-positive-border bg-positive-bg" : "border-caution-border bg-caution-bg"
      } ${className ?? ""}`}
    >
      <p className={`text-sm font-semibold ${allPresent ? "text-stamp" : "text-caution"}`}>{report.advisory_note}</p>
      <ul className="flex flex-col gap-1">
        {report.required.map((docType) => {
          const present = report.present.includes(docType);
          const Icon = present ? CheckCircle2 : CircleDashed;
          return (
            <li key={docType} className={`flex items-center gap-2 text-sm ${present ? "text-foreground" : "text-muted-foreground"}`}>
              <Icon className={`size-4 shrink-0 ${present ? "text-stamp" : "text-ink-muted"}`} aria-hidden="true" />
              {documentTypeLabel[docType]}
              {!present && <span className="text-xs font-medium text-caution">Missing</span>}
            </li>
          );
        })}
      </ul>
      {/* D-35: the checklist itself may not have been checked against an official source. */}
      {!report.verified && (
        <p className="text-xs font-medium text-caution">
          Unverified checklist: this list has not been checked against an official source yet. Your insurer may ask for other documents.
        </p>
      )}
    </div>
  );
}
