import { AlertTriangle, CheckCircle2, HelpCircle, XCircle, type LucideIcon } from "lucide-react";

/**
 * The one semantic-state system every primitive draws from (DESIGN.md).
 * Four tones, each with a colour pair (text + soft background/border) AND an
 * icon, because colour alone is never the only cue — see the accessibility
 * note in DESIGN.md and the greyscale check for /kitchen-sink.
 */
export type StateTone = "positive" | "caution" | "negative" | "neutral";

export const stateIcon: Record<StateTone, LucideIcon> = {
  positive: CheckCircle2,
  caution: AlertTriangle,
  negative: XCircle,
  neutral: HelpCircle,
};

export const stateClasses: Record<StateTone, { text: string; bg: string; border: string }> = {
  positive: {
    text: "text-stamp",
    bg: "bg-positive-bg",
    border: "border-positive-border",
  },
  caution: {
    text: "text-caution",
    bg: "bg-caution-bg",
    border: "border-caution-border",
  },
  negative: {
    text: "text-flag",
    bg: "bg-negative-bg",
    border: "border-negative-border",
  },
  neutral: {
    text: "text-neutral",
    bg: "bg-neutral-bg",
    border: "border-neutral-border",
  },
};
