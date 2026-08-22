/**
 * Loading skeletons match the final layout, never a spinner. Respects
 * prefers-reduced-motion — the pulse becomes a static tint instead of
 * animating.
 */
export interface SkeletonProps {
  className?: string;
}

export function Skeleton({ className }: SkeletonProps) {
  return (
    <div
      role="presentation"
      className={`animate-pulse rounded bg-rule/60 motion-reduce:animate-none ${className ?? "h-4 w-full"}`}
    />
  );
}
