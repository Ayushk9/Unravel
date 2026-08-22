import { Info } from "lucide-react";

/**
 * The system declining to answer, styled as information — never as an
 * error. Always names the missing fact and the document that would resolve
 * it (product rule 3).
 */
export interface AbstentionCardProps {
  missingFact: string;
  resolvingDocument?: string | null;
  action?: { label: string; onClick: () => void };
  className?: string;
}

export function AbstentionCard({ missingFact, resolvingDocument, action, className }: AbstentionCardProps) {
  return (
    <div
      role="status"
      className={`flex items-start gap-3 rounded border border-neutral-border bg-neutral-bg px-4 py-3 ${className ?? ""}`}
    >
      <Info className="mt-0.5 size-5 shrink-0 text-neutral" aria-hidden="true" />
      <div className="flex flex-col gap-1">
        <p className="text-sm font-semibold text-neutral">We don't have enough information yet</p>
        <p className="text-sm text-foreground">{missingFact}</p>
        {resolvingDocument && (
          <p className="text-sm text-muted-foreground">
            Resolved by uploading: <span className="font-medium text-foreground">{resolvingDocument}</span>
          </p>
        )}
        {action && (
          <button
            type="button"
            onClick={action.onClick}
            className="mt-1 self-start rounded border border-neutral-border bg-card px-3 py-1.5 text-sm font-medium text-neutral hover:bg-neutral-bg"
          >
            {action.label}
          </button>
        )}
      </div>
    </div>
  );
}
