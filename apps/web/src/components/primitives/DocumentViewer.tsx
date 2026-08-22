import { useEffect, useRef, useState } from "react";
import { Document, Page } from "react-pdf";
import { ChevronLeft, ChevronRight, FileWarning } from "lucide-react";
import type { DocumentCallback } from "react-pdf/dist/shared/types.js";
import "@/lib/pdf-worker";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import type { Provenance } from "@/api/types";
import { EmptyState } from "./EmptyState";
import { ErrorState } from "./ErrorState";
import { Skeleton } from "./Skeleton";

/**
 * Renders the source PDF and, given a Provenance, jumps to its page and
 * draws the bounding-box highlight. The overlay is positioned in percentages
 * of the rendered page box (not computed pixels), so it tracks react-pdf's
 * layout exactly regardless of container width or device pixel ratio.
 *
 * bbox convention: [x0, y0, x1, y1], normalised 0..1, top-left origin
 * (y grows downward) — matches on-screen/image coordinates, not PDF's
 * native bottom-left origin. Extraction pipelines must emit bbox in this
 * space.
 *
 * If bbox is null, this degrades to a page-level jump with a banner instead
 * of a highlight — see DECISIONS.md for why a wrong-looking highlight is
 * worse than no highlight.
 */
export interface DocumentViewerProps {
  fileUrl: string | null;
  activeProvenance?: Provenance | null;
  className?: string;
}

export function DocumentViewer({ fileUrl, activeProvenance, className }: DocumentViewerProps) {
  const [numPages, setNumPages] = useState<number | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [loadError, setLoadError] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const [pageWidth, setPageWidth] = useState(480);

  useEffect(() => {
    if (activeProvenance) {
      setCurrentPage(activeProvenance.page);
    }
  }, [activeProvenance]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width;
      if (width) setPageWidth(Math.min(width, 720));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  if (!fileUrl) {
    return (
      <EmptyState
        title="No document open"
        description="Click a provenance chip to preview the page it came from."
        className={className}
      />
    );
  }

  if (loadError) {
    return (
      <ErrorState
        message="This document couldn't be opened for preview."
        onRetry={() => {
          setLoadError(false);
          setRetryKey((k) => k + 1);
        }}
        className={className}
      />
    );
  }

  const hasBoxHighlight = activeProvenance?.bbox != null;

  return (
    <div className={`flex flex-col gap-2 ${className ?? ""}`}>
      {activeProvenance && !hasBoxHighlight && (
        <div className="flex items-center gap-2 rounded border border-neutral-border bg-neutral-bg px-3 py-2 text-xs text-neutral">
          <FileWarning className="size-3.5 shrink-0" aria-hidden="true" />
          Jumped to the cited page. An exact highlight isn't available for this extraction.
        </div>
      )}

      <div ref={containerRef} className="w-full">
        <Document
          key={retryKey}
          file={fileUrl}
          onLoadSuccess={(doc: DocumentCallback) => setNumPages(doc.numPages)}
          onLoadError={() => setLoadError(true)}
          loading={<Skeleton className="h-[600px] w-full" />}
        >
          <div className="relative w-fit border border-rule">
            <Page pageNumber={currentPage} width={pageWidth} loading={<Skeleton className="h-[600px] w-full" />} />
            {hasBoxHighlight && activeProvenance?.bbox && (
              <div
                className="pointer-events-none absolute rounded-sm border-2 border-stamp bg-stamp/15"
                style={{
                  left: `${activeProvenance.bbox[0] * 100}%`,
                  top: `${activeProvenance.bbox[1] * 100}%`,
                  width: `${(activeProvenance.bbox[2] - activeProvenance.bbox[0]) * 100}%`,
                  height: `${(activeProvenance.bbox[3] - activeProvenance.bbox[1]) * 100}%`,
                }}
              />
            )}
          </div>
        </Document>
      </div>

      {numPages && (
        <div className="flex items-center justify-center gap-3 text-sm">
          <button
            type="button"
            onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
            disabled={currentPage <= 1}
            aria-label="Previous page"
            className="rounded border border-rule p-1 disabled:opacity-40"
          >
            <ChevronLeft className="size-4" aria-hidden="true" />
          </button>
          <span className="font-tabular font-mono text-xs text-muted-foreground">
            Page {currentPage} of {numPages}
          </span>
          <button
            type="button"
            onClick={() => setCurrentPage((p) => Math.min(numPages, p + 1))}
            disabled={currentPage >= numPages}
            aria-label="Next page"
            className="rounded border border-rule p-1 disabled:opacity-40"
          >
            <ChevronRight className="size-4" aria-hidden="true" />
          </button>
        </div>
      )}
    </div>
  );
}
