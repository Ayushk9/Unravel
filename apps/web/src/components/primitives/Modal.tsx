import { useEffect, type ReactNode } from "react";
import { X } from "lucide-react";

/**
 * Generic modal shell. Used anywhere an action must feel deliberate rather
 * than an inline edit — e.g. appending a claim event, since the event log
 * is append-only and the UI should feel that way (brief §"Timeline tab").
 */
export interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  className?: string;
}

export function Modal({ open, onClose, title, children, className }: ModalProps) {
  useEffect(() => {
    if (!open) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
        className={`flex max-h-[85vh] w-full max-w-md flex-col gap-4 overflow-y-auto rounded border-2 border-ink bg-background p-4 shadow-lg ${className ?? ""}`}
      >
        <div className="flex items-center justify-between gap-3 border-b border-rule pb-2">
          <h2 className="font-serif text-lg font-semibold text-foreground">{title}</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded p-1 text-ink-muted hover:text-foreground">
            <X className="size-4" aria-hidden="true" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
