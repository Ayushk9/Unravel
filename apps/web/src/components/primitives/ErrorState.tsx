import { RefreshCw, TriangleAlert } from "lucide-react";

/** States what failed and gives a retry that actually retries. */
export interface ErrorStateProps {
  message: string;
  requestId?: string | null;
  onRetry: () => void;
  className?: string;
}

export function ErrorState({ message, requestId, onRetry, className }: ErrorStateProps) {
  return (
    <div
      role="alert"
      className={`flex flex-col items-center gap-2 rounded border-2 border-negative-border bg-negative-bg px-6 py-10 text-center ${className ?? ""}`}
    >
      <TriangleAlert className="size-8 text-flag" aria-hidden="true" />
      <p className="font-serif text-base font-semibold text-flag">Something went wrong</p>
      <p className="max-w-prose text-sm text-foreground">{message}</p>
      {requestId && <p className="font-mono text-xs text-muted-foreground">Reference: {requestId}</p>}
      <button
        type="button"
        onClick={onRetry}
        className="mt-2 inline-flex items-center gap-1.5 rounded border border-negative-border bg-card px-3 py-1.5 text-sm font-medium text-foreground hover:bg-negative-bg"
      >
        <RefreshCw className="size-3.5" aria-hidden="true" />
        Try again
      </button>
    </div>
  );
}
