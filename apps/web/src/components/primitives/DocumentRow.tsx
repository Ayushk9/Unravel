import { Eye, Loader2, Trash2 } from "lucide-react";
import type { DocumentType, StoredDocument } from "@/api/types";
import { formatISTDate } from "@/lib/formatDate";
import { DocumentTypeSelect } from "./DocumentTypeSelect";

const parseStatusLabel: Record<StoredDocument["parse_status"], string> = {
  queued: "Queued",
  parsing: "Parsing…",
  parsed: "Parsed",
  failed: "Failed to parse",
  unknown: "Status unknown",
};

export interface DocumentRowProps {
  document: StoredDocument;
  onTypeChange?: (type: DocumentType) => void;
  onView?: () => void;
  onDelete?: () => void;
  pending?: boolean;
  className?: string;
}

/** One uploaded document — used by the claim wizard's Documents step and the claim workspace's Documents tab. */
export function DocumentRow({ document, onTypeChange, onView, onDelete, pending = false, className }: DocumentRowProps) {
  const parsed = document.parse_status === "parsed";
  const stillWorking = document.parse_status === "queued" || document.parse_status === "parsing";

  return (
    <div className={`flex flex-wrap items-center justify-between gap-2 rounded border border-rule bg-card px-3 py-2.5 ${className ?? ""}`}>
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="truncate text-sm font-medium text-foreground">{document.file_name}</span>
        <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
          {stillWorking && <Loader2 className="size-3 shrink-0 animate-spin motion-reduce:animate-none" aria-hidden="true" />}
          {parseStatusLabel[document.parse_status]} · Uploaded {formatISTDate(document.uploaded_at)}
        </span>
      </div>

      <div className="flex items-center gap-2">
        <DocumentTypeSelect
          value={document.detected_type.value ?? "unknown"}
          onChange={(t) => onTypeChange?.(t)}
          disabled={!parsed || !onTypeChange || pending}
        />
        {onView && (
          <button
            type="button"
            onClick={onView}
            disabled={!parsed}
            aria-label={`View ${document.file_name}`}
            className="rounded border border-rule p-1.5 text-ink-muted hover:text-foreground disabled:opacity-40"
          >
            <Eye className="size-4" aria-hidden="true" />
          </button>
        )}
        {onDelete && (
          <button
            type="button"
            onClick={onDelete}
            aria-label={`Delete ${document.file_name}`}
            className="rounded border border-rule p-1.5 text-ink-muted hover:text-flag"
          >
            <Trash2 className="size-4" aria-hidden="true" />
          </button>
        )}
      </div>
    </div>
  );
}
