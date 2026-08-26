import type { BillLineItem, Provenance, ValidationFlag } from "@/api/types";
import { ids } from "./ids";

function prov(page: number, snippet: string): Provenance {
  return { document_id: ids.document.deniedBill, page, bbox: null, snippet };
}

/**
 * 18 line items on the denied claim's itemised bill, three of them planted
 * defects (brief §6.1's exact scenario): surgical gloves as a non-payable
 * consumable, a duplicated OT charges row, and room rent at ₹12,000/day
 * against the retail policy's ₹5,000/day cap (mocks/fixtures/policies.ts) —
 * same figure, not a coincidence.
 */
export const deniedClaimBillLineItems: BillLineItem[] = [
  { id: "bill-item-01", description: "Room rent (5 days)", quantity: 5, rate: 12_000_00, amount: 60_000_00, provenance: prov(1, "Room Rent 5 days @ Rs.12,000") },
  { id: "bill-item-02", description: "ICU charges", quantity: 1, rate: 8_000_00, amount: 8_000_00, provenance: prov(1, "ICU Charges") },
  { id: "bill-item-03", description: "Nursing charges (5 days)", quantity: 5, rate: 1_500_00, amount: 7_500_00, provenance: prov(1, "Nursing Charges") },
  { id: "bill-item-04", description: "Surgeon's fee", quantity: 1, rate: 45_000_00, amount: 45_000_00, provenance: prov(1, "Surgeon Fee") },
  { id: "bill-item-05", description: "Anaesthetist's fee", quantity: 1, rate: 12_000_00, amount: 12_000_00, provenance: prov(1, "Anaesthetist Fee") },
  { id: "bill-item-06", description: "OT charges", quantity: 1, rate: 18_000_00, amount: 18_000_00, provenance: prov(1, "OT Charges") },
  { id: "bill-item-07", description: "OT charges", quantity: 1, rate: 18_000_00, amount: 18_000_00, provenance: prov(2, "OT Charges") },
  { id: "bill-item-08", description: "Consumables", quantity: 1, rate: 6_500_00, amount: 6_500_00, provenance: prov(2, "Consumables") },
  { id: "bill-item-09", description: "Surgical gloves", quantity: 1, rate: 4_200_00, amount: 4_200_00, provenance: prov(2, "Surgical Gloves") },
  { id: "bill-item-10", description: "Investigation — blood tests", quantity: 1, rate: 3_200_00, amount: 3_200_00, provenance: prov(2, "Lab — Blood Tests") },
  { id: "bill-item-11", description: "Investigation — X-Ray", quantity: 1, rate: 1_800_00, amount: 1_800_00, provenance: prov(2, "Radiology — X-Ray") },
  { id: "bill-item-12", description: "Investigation — MRI", quantity: 1, rate: 9_500_00, amount: 9_500_00, provenance: prov(2, "Radiology — MRI") },
  { id: "bill-item-13", description: "Pharmacy (inpatient)", quantity: 1, rate: 14_300_00, amount: 14_300_00, provenance: prov(2, "Pharmacy") },
  { id: "bill-item-14", description: "Pharmacy (post-discharge)", quantity: 1, rate: 2_100_00, amount: 2_100_00, provenance: prov(2, "Pharmacy — Take Home") },
  { id: "bill-item-15", description: "Physiotherapy (3 sessions)", quantity: 3, rate: 1_000_00, amount: 3_000_00, provenance: prov(2, "Physiotherapy") },
  { id: "bill-item-16", description: "Dietician charges", quantity: 1, rate: 1_200_00, amount: 1_200_00, provenance: prov(2, "Dietician") },
  { id: "bill-item-17", description: "Registration / admission fee", quantity: 1, rate: 500_00, amount: 500_00, provenance: prov(1, "Registration Fee") },
  { id: "bill-item-18", description: "Ambulance charges", quantity: 1, rate: 2_500_00, amount: 2_500_00, provenance: prov(2, "Ambulance") },
];

export const deniedClaimBillFlags: ValidationFlag[] = [
  {
    severity: "error",
    rule: "sub_limit_breach",
    message:
      "Room rent of ₹12,000/day is above your policy's ₹5,000/day cap. Charges above a room-rent cap can also trigger a proportionate deduction across the rest of the bill, not just this line — check your policy wording.",
    line_item_ids: ["bill-item-01"],
    estimated_impact: 35_000_00, // (12,000 - 5,000) * 5 days
  },
  {
    severity: "warning",
    rule: "duplicate_line",
    message: "\"OT charges\" appears twice for the same amount — likely entered in error.",
    line_item_ids: ["bill-item-06", "bill-item-07"],
    estimated_impact: 18_000_00,
  },
  {
    severity: "warning",
    rule: "non_payable_item",
    message: "Surgical gloves are a non-payable consumable under standard policy terms.",
    line_item_ids: ["bill-item-09"],
    estimated_impact: 4_200_00,
  },
];

export const deniedClaimBillTotalBilled = deniedClaimBillLineItems.reduce((sum, item) => sum + item.amount, 0);
export const deniedClaimBillTotalAtRisk = deniedClaimBillFlags.reduce((sum, flag) => sum + (flag.estimated_impact ?? 0), 0);
