/**
 * Centralised TanStack Query key factory. New resource keys are added here as
 * their endpoint module is built — see src/api/endpoints/*.
 */
export const queryKeys = {
  health: () => ["health"] as const,
};
