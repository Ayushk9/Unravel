import { useState } from "react";
import { ChevronDown, UploadCloud } from "lucide-react";
import type { EligibilityCheck, Provenance } from "@/api/types";
import { ProvenanceChip } from "./ProvenanceChip";
import { stateClasses, stateIcon, type StateTone } from "./state";
import { documentTypeLabel } from "./DocumentTypeSelect";

const statusTone: Record<EligibilityCheck["status"], StateTone> = {
  satisfied: "positive",
  at_risk: "caution",
  failed: "negative",
  unknown: "neutral",
};

const statusLabel: Record<EligibilityCheck["status"], string> = {
  satisfied: "Satisfied",
  at_risk: "At risk",
  failed: "Not satisfied",
  unknown: "Unknown",
};

export interface EligibilityCheckItemProps {
  check: EligibilityCheck;
  onOpenProvenance?: (provenance: Provenance) => void;
  onUploadResolvingDocument?: (check: EligibilityCheck) => void;
  defaultExpanded?: boolean;
  className?: string;
}

/**
 * One row in the eligibility checks list — expandable, status-toned (never
 * colour-alone: icon + text label carry the meaning too, for the greyscale
 * check). `unknown` checks surface their missing fact and, when a resolving
 * document type is known, a button to go upload it.
 */
export function EligibilityCheckItem({
  check,
  onOpenProvenance,
  onUploadResolvingDocument,
  defaultExpanded = false,
  className,
}: EligibilityCheckItemProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const tone = statusTone[check.status];
  const c = stateClasses[tone];
  const Icon = stateIcon[tone];

  return (
    <div className={`rounded border ${c.border} bg-card ${className ?? ""}`}>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
      >
        <Icon className={`size-5 shrink-0 ${c.text}`} aria-hidden="true" />
        <div className="flex flex-1 flex-col">
          <span className="font-serif text-sm font-semibold text-foreground">{check.title}</span>
          <span className={`text-xs font-medium ${c.text}`}>{statusLabel[check.status]}</span>
        </div>
        <ChevronDown className={`size-4 shrink-0 text-ink-muted transition-transform ${expanded ? "rotate-180" : ""}`} aria-hidden="true" />
      </button>

      {expanded && (
        <div className="flex flex-col gap-2 border-t border-rule px-4 py-3">
          <p className="text-sm text-foreground">{check.explanation}</p>

          {/* EligibilityCheck.governing_clause is a bare Provenance (D-14's Extracted<T> wrapper, with its confidence/user_confirmed, lives on the source coverage-profile field, not here) — so this never claims "verified" for something nobody actually confirmed. */}
          {check.governing_clause && <ProvenanceChip provenance={check.governing_clause} userConfirmed={false} onOpen={onOpenProvenance} />}

          {check.status === "unknown" && check.missing_fact && (
            <div className="mt-1 flex flex-col gap-1.5 rounded border border-dashed border-neutral-border bg-neutral-bg px-3 py-2">
              <span className="text-sm text-neutral">Missing: {check.missing_fact}</span>
              {check.resolving_document && onUploadResolvingDocument && (
                <button
                  type="button"
                  onClick={() => onUploadResolvingDocument(check)}
                  className="inline-flex w-fit items-center gap-1.5 rounded border border-neutral-border bg-card px-2 py-1 text-xs font-medium text-neutral hover:bg-neutral-bg"
                >
                  <UploadCloud className="size-3.5" aria-hidden="true" />
                  Upload {documentTypeLabel[check.resolving_document]}
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
