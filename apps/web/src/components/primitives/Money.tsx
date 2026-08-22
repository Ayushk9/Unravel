import type { Paise } from "@/api/types";

/**
 * The only place Intl.NumberFormat('en-IN') or a ₹ symbol appears. Every rupee
 * value elsewhere in the app must flow through this component — never format
 * money inline.
 *
 * `compact` switches to lakh/crore shorthand for space-constrained UI (table
 * cells, chips). Threshold: below ₹1,00,000 compact still shows the full
 * amount (there's no shorter form worth using yet); ₹1,00,000–₹99,99,999
 * shows "₹X.XXL"; ₹1,00,00,000 and above shows "₹X.XXCr".
 */

const fullFormatter = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

const LAKH = 100_000_00; // paise
const CRORE = 100_00_000_00; // paise

function formatCompact(paise: number): string {
  const rupees = paise / 100;
  if (Math.abs(paise) >= CRORE) {
    return `₹${(rupees / 1_00_00_000).toFixed(2)}Cr`;
  }
  if (Math.abs(paise) >= LAKH) {
    return `₹${(rupees / 1_00_000).toFixed(2)}L`;
  }
  return fullFormatter.format(rupees);
}

export interface MoneyProps {
  value: Paise | null;
  compact?: boolean;
  className?: string;
}

export function Money({ value, compact = false, className }: MoneyProps) {
  if (value === null) {
    return (
      <span className={`font-mono text-muted-foreground ${className ?? ""}`} aria-label="Amount not available">
        —
      </span>
    );
  }

  const text = compact ? formatCompact(value) : fullFormatter.format(value / 100);

  return (
    <span className={`font-tabular font-mono ${className ?? ""}`}>
      {text}
    </span>
  );
}
