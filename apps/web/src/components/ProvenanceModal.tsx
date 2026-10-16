import type { Provenance } from "@/api/types";
import { useDocumentFile } from "@/api/endpoints/documents";
import { DocumentViewer, ErrorState, Modal, Skeleton } from "@/components/primitives";

export interface ProvenanceModalProps {
  provenance: Provenance | null;
  onClose: () => void;
  title: string;
}

/**
 * Opens the document a provenance points at, on its page, with the line
 * highlighted. The file comes from GET /documents/{id}/file (D-26), so the
 * highlight lands on the user's real document, not a sample PDF.
 */
export function ProvenanceModal({ provenance, onClose, title }: ProvenanceModalProps) {
  const file = useDocumentFile(provenance?.document_id ?? null);

  return (
    <Modal open={provenance !== null} onClose={onClose} title={title}>
      {file.isPending && <Skeleton className="h-96 w-full" />}
      {file.isError && <ErrorState message="We couldn't open that document. Try again." onRetry={() => file.refetch()} />}
      {file.isSuccess && <DocumentViewer fileUrl={file.data.url} activeProvenance={provenance} />}
    </Modal>
  );
}
