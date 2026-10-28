import { Construction } from "lucide-react";

/**
 * A one-line screen for an address with nothing behind it: a feature that is
 * not part of this version, or a page that doesn't exist. It states plainly
 * what is there and never promises when something will arrive.
 */
export interface PlaceholderScreenProps {
  title: string;
  message: string;
}

export function PlaceholderScreen({ title, message }: PlaceholderScreenProps) {
  return (
    <div className="flex flex-col items-center gap-2 rounded border border-dashed border-rule px-6 py-16 text-center">
      <Construction className="size-8 text-ink-muted" aria-hidden="true" />
      <h1 className="font-serif text-xl font-semibold text-foreground">{title}</h1>
      <p className="text-sm text-muted-foreground">{message}</p>
    </div>
  );
}
