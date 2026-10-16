import type { Household } from "@/api/types";

/** D-40: no city tier chosen yet, so the room-rent alert would be skipped by the real backend. */
export const household: Household = { id: "household-rao", name: "Rao household", city_tier: null };
