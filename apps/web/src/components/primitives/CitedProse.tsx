import type { Citation } from "@/api/types";

const MARKER_PATTERN = /\[\[(\d+)\]\]/g;

export interface CitedProseProps {
  text: string;
  citations: Citation[];
  onOpenCitation?: (citation: Citation) => void;
  className?: string;
}

/**
 * Renders prose with inline superscript citation markers. The mock embeds
 * `[[n]]` tokens (n = 1-indexed position in `citations`) in the generated
 * text — see mocks/handlers/policies.ts. A real backend just needs to emit
 * the same marker shape; this component doesn't care how the text was
 * generated, only that every claim traces to a citation. Never render
 * confident prose without at least one marker — the caller is responsible
 * for showing the abstention primitive instead when there's nothing to cite.
 */
export function CitedProse({ text, citations, onOpenCitation, className }: CitedProseProps) {
  const parts: (string | { citationIndex: number })[] = [];
  let lastIndex = 0;
  for (const match of text.matchAll(MARKER_PATTERN)) {
    const index = match.index;
    if (index > lastIndex) parts.push(text.slice(lastIndex, index));
    parts.push({ citationIndex: Number.parseInt(match[1]!, 10) - 1 });
    lastIndex = index + match[0].length;
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex));

  return (
    <p className={`text-base leading-relaxed text-foreground ${className ?? ""}`}>
      {parts.map((part, i) => {
        if (typeof part === "string") return <span key={i}>{part}</span>;
        const citation = citations[part.citationIndex];
        if (!citation) return null;
        return (
          <button
            key={i}
            type="button"
            onClick={() => onOpenCitation?.(citation)}
            className="mx-0.5 -translate-y-1 rounded px-0.5 font-mono text-xs text-stamp underline decoration-dotted underline-offset-2 hover:bg-positive-bg"
            aria-label={`Open citation: ${citation.label}`}
          >
            [{part.citationIndex + 1}]
          </button>
        );
      })}
    </p>
  );
}
