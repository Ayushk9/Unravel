import type { Policy } from "@/api/types";

/**
 * Display text for the policy fields that can be null (API_DECISIONS D-25).
 * A policy built from an uploaded document only knows what the document
 * stated, so each of these says plainly that the detail is missing rather
 * than showing a blank or a made-up value.
 */
export function insurerLabel(policy: Pick<Policy, "insurer">): string {
  return policy.insurer?.name ?? "Insurer not stated";
}

export function productLabel(policy: Pick<Policy, "product_name">): string {
  return policy.product_name ?? "Product name not stated";
}

export function policyNumberLabel(policy: Pick<Policy, "policy_number">): string {
  return policy.policy_number ?? "not stated";
}
