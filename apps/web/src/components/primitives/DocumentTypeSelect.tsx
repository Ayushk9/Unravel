import type { DocumentType } from "@/api/types";

export const documentTypeLabel: Record<DocumentType, string> = {
  policy_schedule: "Policy schedule",
  policy_wording: "Policy wording",
  discharge_summary: "Discharge summary",
  itemised_bill: "Itemised bill",
  payment_receipt: "Payment receipt",
  investigation_report: "Investigation report",
  denial_letter: "Denial letter",
  id_proof: "ID proof",
  unknown: "Unknown",
};

const SELECTABLE_TYPES: DocumentType[] = [
  "discharge_summary",
  "itemised_bill",
  "payment_receipt",
  "investigation_report",
  "denial_letter",
  "id_proof",
  "policy_schedule",
  "policy_wording",
  "unknown",
];

export interface DocumentTypeSelectProps {
  value: DocumentType;
  onChange: (value: DocumentType) => void;
  disabled?: boolean;
  className?: string;
}

/** Editable dropdown for a document's auto-detected type — the claim wizard's Documents step and the claim workspace's Documents tab both let the user correct a misclassification through this. */
export function DocumentTypeSelect({ value, onChange, disabled, className }: DocumentTypeSelectProps) {
  return (
    <select
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value as DocumentType)}
      aria-label="Document type"
      className={`rounded border border-rule bg-background px-2 py-1 text-sm disabled:opacity-50 ${className ?? ""}`}
    >
      {SELECTABLE_TYPES.map((t) => (
        <option key={t} value={t}>
          {documentTypeLabel[t]}
        </option>
      ))}
    </select>
  );
}
