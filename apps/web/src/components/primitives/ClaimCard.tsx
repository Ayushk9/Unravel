import { Link } from "react-router-dom";
import { Building2 } from "lucide-react";
import type { Claim, Member } from "@/api/types";
import { formatISTDate } from "@/lib/formatDate";
import { ClaimStateBadge } from "./ClaimStateBadge";
import { DeadlineCard } from "./DeadlineCard";

const claimTypeLabel: Record<Claim["claim_type"], string> = {
  cashless: "Cashless",
  reimbursement: "Reimbursement",
  other: "Other",
};

export interface ClaimCardProps {
  claim: Claim;
  member?: Member | null;
  className?: string;
}

/** Summary card for /claims — any claim with an active deadline surfaces it here, urgency-styled via DeadlineCard. */
export function ClaimCard({ claim, member, className }: ClaimCardProps) {
  const primaryDeadline = claim.deadlines[0] ?? null;

  return (
    <Link
      to={`/claims/${claim.id}`}
      className={`flex flex-col gap-2 rounded border border-rule bg-card px-4 py-3 transition-colors hover:border-ink ${className ?? ""}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <Building2 className="size-4 shrink-0 text-ink-muted" aria-hidden="true" />
          <span className="font-serif text-base font-semibold text-foreground">{claim.hospital_name}</span>
        </div>
        <ClaimStateBadge state={claim.current_state} />
      </div>

      <p className="text-sm text-muted-foreground">
        {claimTypeLabel[claim.claim_type]}
        {member ? ` · ${member.full_name}` : ""}
      </p>

      {(claim.admitted_on || claim.discharged_on) && (
        <p className="font-tabular font-mono text-xs text-muted-foreground">
          {claim.admitted_on ? formatISTDate(claim.admitted_on) : "—"} – {claim.discharged_on ? formatISTDate(claim.discharged_on) : "—"}
        </p>
      )}

      {primaryDeadline && <DeadlineCard deadline={primaryDeadline} />}
    </Link>
  );
}
