import { BookOpen, ExternalLink, FileQuestion, FileText, Scale } from "lucide-react";
import type { Citation } from "@/api/types";

const kindIcon: Record<Citation["kind"], typeof FileText> = {
  policy_clause: FileText,
  regulation: BookOpen,
  ombudsman_award: Scale,
  other: FileQuestion,
};

const kindLabel: Record<Citation["kind"], string> = {
  policy_clause: "Your policy",
  regulation: "Regulation",
  ombudsman_award: "Ombudsman award",
  other: "Source",
};

export interface CitationListProps {
  citations: Citation[];
  onOpenProvenance?: (citation: Citation) => void;
  className?: string;
}

/** Numbered, footnote-style — matches the superscript markers in grounded Q&A and grievance text. */
export function CitationList({ citations, onOpenProvenance, className }: CitationListProps) {
  if (citations.length === 0) {
    return <p className="text-sm text-muted-foreground">No citations yet.</p>;
  }

  return (
    <ol className={`flex flex-col gap-2 ${className ?? ""}`}>
      {citations.map((citation, index) => {
        const Icon = kindIcon[citation.kind];
        const isOpenable = citation.provenance && onOpenProvenance;

        return (
          <li key={citation.id} className="flex items-start gap-2 rounded border border-rule bg-card px-3 py-2 text-sm">
            <span className="font-tabular mt-0.5 font-mono text-xs text-muted-foreground">{index + 1}</span>
            <Icon className="mt-0.5 size-4 shrink-0 text-ink-muted" aria-hidden="true" />
            <div className="flex flex-1 flex-col">
              <span className="text-xs tracking-wide text-muted-foreground uppercase">{kindLabel[citation.kind]}</span>
              {isOpenable ? (
                <button
                  type="button"
                  onClick={() => onOpenProvenance(citation)}
                  className="text-left text-foreground underline decoration-rule underline-offset-2 hover:decoration-ink"
                >
                  {citation.label}
                </button>
              ) : citation.external_url ? (
                <a
                  href={citation.external_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-foreground underline decoration-rule underline-offset-2 hover:decoration-ink"
                >
                  {citation.label}
                  <ExternalLink className="size-3" aria-hidden="true" />
                </a>
              ) : (
                <span className="text-foreground">{citation.label}</span>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
