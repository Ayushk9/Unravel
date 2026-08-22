import { pdfjs } from "react-pdf";

// Vite-bundled worker, no CDN dependency — see react-pdf's Vite setup docs.
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();
