import { AlertTriangle, BadgeCheck, HelpCircle } from "lucide-react";
import type { Provenance } from "@/api/types";

/**
 * The signature element (DESIGN.md): a ticket-stub chip that proves a fact
 * came from the user's own document. Three states, and the distinction
 * between them is a product-integrity rule, not a styling choice:
 *
 * - "verified": has provenance AND user_confirmed. Filled, stamp-toned,
 *   clickable — opens the document viewer to the source page.
 * - "unconfirmed": has provenance but the user hasn't confirmed it yet.
 *   Dashed outline, caution-toned, still clickable so the user can go check
 *   it against the source themselves.
 * - "unverified": no provenance at all. Dashed outline, neutral-toned,
 *   NOT clickable — there is nothing to open. This can never render as
 *   confirmed, per the rule that missing provenance is always unverified.
 */
export type ProvenanceState = "verified" | "unconfirmed" | "unverified";

export function provenanceState(provenance: Provenance | null, userConfirmed: boolean): ProvenanceState {
  if (!provenance) return "unverified";
  return userConfirmed ? "verified" : "unconfirmed";
}

const variant: Record<
  ProvenanceState,
  { label: (page?: number) => string; icon: typeof BadgeCheck; classes: string; dashed: boolean }
> = {
  verified: {
    label: (page) => `Verified · p.${page}`,
    icon: BadgeCheck,
    classes: "border-positive-border bg-positive-bg text-stamp",
    dashed: false,
  },
  unconfirmed: {
    label: (page) => `Unconfirmed · p.${page}`,
    icon: AlertTriangle,
    classes: "border-caution-border bg-caution-bg text-caution",
    dashed: true,
  },
  unverified: {
    label: () => "Unverified — no source",
    icon: HelpCircle,
    classes: "border-neutral-border bg-neutral-bg text-neutral",
    dashed: true,
  },
};

export interface ProvenanceChipProps {
  provenance: Provenance | null;
  userConfirmed?: boolean;
  onOpen?: (provenance: Provenance) => void;
  className?: string;
}

export function ProvenanceChip({ provenance, userConfirmed = false, onOpen, className }: ProvenanceChipProps) {
  const state = provenanceState(provenance, userConfirmed);
  const v = variant[state];
  const Icon = v.icon;

  const content = (
    <>
      <Icon className="size-3.5 shrink-0" aria-hidden="true" />
      <span>{v.label(provenance?.page)}</span>
    </>
  );

  const sharedClasses = `inline-flex items-center gap-1.5 rounded-sm border px-2 py-1 text-xs font-medium ${v.classes} ${
    v.dashed ? "border-dashed" : ""
  } ${className ?? ""}`;

  if (state === "unverified" || !provenance) {
    return (
      <span className={`${sharedClasses} cursor-not-allowed`} aria-label={v.label()}>
        {content}
      </span>
    );
  }

  return (
    <button
      type="button"
      onClick={() => onOpen?.(provenance)}
      className={`${sharedClasses} cursor-pointer transition-colors hover:brightness-95 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring`}
    >
      {content}
    </button>
  );
}
