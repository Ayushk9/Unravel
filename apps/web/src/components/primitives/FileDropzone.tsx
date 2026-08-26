import { useRef, useState } from "react";
import { UploadCloud } from "lucide-react";

export interface FileDropzoneProps {
  accept?: string;
  maxBytes?: number;
  onFileSelected: (file: File) => void;
  className?: string;
}

export function FileDropzone({ accept = "application/pdf,image/*", maxBytes = 25 * 1024 * 1024, onFileSelected, className }: FileDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleFile(file: File | undefined) {
    if (!file) return;
    if (file.size > maxBytes) {
      setError(`"${file.name}" is larger than 25 MB. Choose a smaller file.`);
      return;
    }
    setError(null);
    onFileSelected(file);
  }

  return (
    <div className={className}>
      <div
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          handleFile(e.dataTransfer.files[0]);
        }}
        className={`flex cursor-pointer flex-col items-center gap-2 rounded border-2 border-dashed px-6 py-12 text-center transition-colors ${
          dragging ? "border-stamp bg-positive-bg" : "border-rule hover:border-ink"
        }`}
      >
        <UploadCloud className="size-8 text-ink-muted" aria-hidden="true" />
        <p className="text-sm font-medium text-foreground">Drag a file here, or click to choose one</p>
        <p className="text-xs text-muted-foreground">PDF or a photo of your policy schedule — up to 25 MB</p>
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          className="sr-only"
          onChange={(e) => handleFile(e.target.files?.[0])}
        />
      </div>
      {error && <p className="mt-2 text-sm text-flag">{error}</p>}
    </div>
  );
}
