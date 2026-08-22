import type { LucideIcon } from "lucide-react";
import { Inbox } from "lucide-react";

/** An invitation to act, not a dead end — the action lives in place. */
export interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  description: string;
  action?: { label: string; onClick: () => void };
  className?: string;
}

export function EmptyState({ icon: Icon = Inbox, title, description, action, className }: EmptyStateProps) {
  return (
    <div
      className={`flex flex-col items-center gap-2 rounded border border-dashed border-rule px-6 py-10 text-center ${className ?? ""}`}
    >
      <Icon className="size-8 text-ink-muted" aria-hidden="true" />
      <p className="font-serif text-base font-semibold text-foreground">{title}</p>
      <p className="max-w-prose text-sm text-muted-foreground">{description}</p>
      {action && (
        <button
          type="button"
          onClick={action.onClick}
          className="mt-2 rounded bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/85"
        >
          {action.label}
        </button>
      )}
    </div>
  );
}
