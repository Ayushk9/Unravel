/**
 * Domain types. Hand-written and authoritative until the backend ships its first
 * FastAPI route — see docs/API_DECISIONS.md D-21. From that point on this file is
 * replaced by generated output from packages/contracts-ts, not maintained in parallel.
 *
 * snake_case throughout, matching the wire format exactly (D-02) — no camelCase
 * transform at this boundary.
 */
export * from "@internal/contracts-ts";
