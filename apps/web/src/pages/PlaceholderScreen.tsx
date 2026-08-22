import { Construction } from "lucide-react";

/**
 * Stands in for routes not built yet — see docs/claude-code-frontend-prompt.md
 * §10 for which phase builds each one. Exists only so nav + responsive layout
 * have somewhere real to go; never claims a feature works before it does.
 */
export interface PlaceholderScreenProps {
  title: string;
  phase: string;
}

export function PlaceholderScreen({ title, phase }: PlaceholderScreenProps) {
  return (
    <div className="flex flex-col items-center gap-2 rounded border border-dashed border-rule px-6 py-16 text-center">
      <Construction className="size-8 text-ink-muted" aria-hidden="true" />
      <h1 className="font-serif text-xl font-semibold text-foreground">{title}</h1>
      <p className="text-sm text-muted-foreground">Not built yet — arrives in {phase}.</p>
    </div>
  );
}
