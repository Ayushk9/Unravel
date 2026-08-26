import { Check } from "lucide-react";

export interface WizardStep {
  key: string;
  label: string;
}

export interface WizardStepsProps {
  steps: WizardStep[];
  currentIndex: number;
  className?: string;
}

/** Generalises JobProgress's stage indicator to N steps — the claim wizard's progress rail. */
export function WizardSteps({ steps, currentIndex, className }: WizardStepsProps) {
  return (
    <ol className={`flex items-center gap-1 ${className ?? ""}`}>
      {steps.map((step, i) => {
        const done = i < currentIndex;
        const active = i === currentIndex;
        return (
          <li key={step.key} className="flex flex-1 items-center gap-1.5">
            <span
              className={`flex size-6 shrink-0 items-center justify-center rounded-full border-2 text-xs font-semibold ${
                done
                  ? "border-stamp bg-stamp text-primary-foreground"
                  : active
                    ? "border-stamp text-stamp"
                    : "border-rule text-muted-foreground"
              }`}
            >
              {done ? <Check className="size-3.5" aria-hidden="true" /> : i + 1}
            </span>
            <span className={`hidden text-xs sm:inline ${active ? "font-semibold text-foreground" : "text-muted-foreground"}`}>
              {step.label}
            </span>
            {i < steps.length - 1 && <span className="h-px flex-1 bg-rule" aria-hidden="true" />}
          </li>
        );
      })}
    </ol>
  );
}
