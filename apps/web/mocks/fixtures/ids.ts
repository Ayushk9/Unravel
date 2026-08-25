/**
 * Central id constants so fixture cross-references (a bill's room-rent flag
 * pointing at the same figure as an alert, a claim pointing at its policy)
 * can't drift apart through a typo. Not real UUIDv7s — the backend generates
 * those (D-11); these are readable fixture ids, which is fine because the
 * frontend treats ids as opaque strings.
 */
export const ids = {
  insurer: {
    group: "insurer-kavach-health",
    retail: "insurer-suraksha-general",
    bench3: "insurer-nirvaan-health",
    bench4: "insurer-bharosa-general",
    bench5: "insurer-sanjeevani-health",
    bench6: "insurer-rakshak-general",
    bench7: "insurer-arogya-mitra",
    bench8: "insurer-vishwas-general",
    bench9: "insurer-shubham-health",
    bench10: "insurer-poorna-suraksha",
  },
  member: {
    self: "member-self",
    spouse: "member-spouse",
    child: "member-child",
    parent: "member-parent",
  },
  policy: {
    group: "policy-group-floater",
    retail: "policy-retail-individual",
  },
  document: {
    groupSchedule: "doc-group-policy-schedule",
    retailSchedule: "doc-retail-policy-schedule",
    retailWording: "doc-retail-policy-wording",
    deniedDischarge: "doc-denied-claim-discharge-summary",
    deniedBill: "doc-denied-claim-itemised-bill",
    deniedDenialLetter: "doc-denied-claim-denial-letter",
    underReviewDischarge: "doc-under-review-discharge-summary",
    underReviewIdProof: "doc-under-review-id-proof",
    underReviewReceipt: "doc-under-review-payment-receipt",
    settledDischarge: "doc-settled-discharge-summary",
    settledBill: "doc-settled-itemised-bill",
  },
  claim: {
    denied: "claim-denied-ped",
    underReview: "claim-under-review",
    settled: "claim-settled",
  },
} as const;
