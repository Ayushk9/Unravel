import { useState, type ReactNode } from "react";
import { Check, Pencil } from "lucide-react";
import type { Confidence, Provenance } from "@/api/types";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { ProvenanceChip } from "./ProvenanceChip";

/**
 * Every extracted field in the product renders through this — label, value,
 * confidence, provenance, and (when correctable) inline confirm/correct
 * controls, all in one consistent shape. This is what "every extracted
 * value renders through <ConfidenceBadge> + <ProvenanceChip>" (Phase 3
 * binding constraint) actually means in practice: one primitive, not four
 * ad-hoc renderings across the upload-review and policy-detail screens.
 *
 * Correction is plumbed as a raw string (`onCorrect`) rather than a generic
 * `<T>` — callers already know how to parse their own field (paise, a
 * percentage, a month count) and this keeps the primitive free of generics.
 */
export interface ExtractedFieldProps {
  label: string;
  valueDisplay: ReactNode;
  confidence: Confidence;
  userConfirmed: boolean;
  provenance: Provenance | null;
  snippet?: string | null;
  onOpenProvenance?: (provenance: Provenance) => void;
  /** Omit both to render read-only (e.g. exclusions, which this mock doesn't support correcting). */
  onConfirm?: () => void;
  onCorrect?: (rawValue: string) => void;
  correctPlaceholder?: string;
  pending?: boolean;
  className?: string;
}

export function ExtractedField({
  label,
  valueDisplay,
  confidence,
  userConfirmed,
  provenance,
  snippet,
  onOpenProvenance,
  onConfirm,
  onCorrect,
  correctPlaceholder,
  pending = false,
  className,
}: ExtractedFieldProps) {
  const [correcting, setCorrecting] = useState(false);
  const [draft, setDraft] = useState("");
  const canAct = (onConfirm || onCorrect) && !userConfirmed;

  return (
    <div className={`flex flex-col gap-1.5 rounded border border-rule bg-card px-3 py-2.5 ${className ?? ""}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
        <ConfidenceBadge confidence={confidence} userConfirmed={userConfirmed} />
      </div>

      <div className="font-serif text-lg text-foreground">{valueDisplay}</div>

      {snippet && <p className="text-xs text-muted-foreground italic">"{snippet}"</p>}

      <div className="flex flex-wrap items-center gap-2">
        <ProvenanceChip provenance={provenance} userConfirmed={userConfirmed} onOpen={onOpenProvenance} />

        {canAct && !correcting && (
          <div className="ml-auto flex items-center gap-1.5">
            {onConfirm && (
              <button
                type="button"
                onClick={onConfirm}
                disabled={pending}
                className="inline-flex items-center gap-1 rounded border border-positive-border bg-positive-bg px-2 py-1 text-xs font-medium text-stamp hover:brightness-95 disabled:opacity-50"
              >
                <Check className="size-3" aria-hidden="true" />
                Confirm
              </button>
            )}
            {onCorrect && (
              <button
                type="button"
                onClick={() => setCorrecting(true)}
                disabled={pending}
                className="inline-flex items-center gap-1 rounded border border-rule px-2 py-1 text-xs font-medium text-foreground hover:bg-secondary disabled:opacity-50"
              >
                <Pencil className="size-3" aria-hidden="true" />
                Correct
              </button>
            )}
          </div>
        )}
      </div>

      {correcting && onCorrect && (
        <form
          className="mt-1 flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            onCorrect(draft);
            setCorrecting(false);
            setDraft("");
          }}
        >
          <input
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={correctPlaceholder}
            className="w-full rounded border border-rule bg-background px-2 py-1 text-sm"
          />
          <button type="submit" disabled={pending} className="rounded bg-primary px-2 py-1 text-xs font-medium text-primary-foreground disabled:opacity-50">
            Save
          </button>
          <button type="button" onClick={() => setCorrecting(false)} className="rounded border border-rule px-2 py-1 text-xs">
            Cancel
          </button>
        </form>
      )}
    </div>
  );
}
