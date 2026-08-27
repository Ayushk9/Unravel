import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router-dom";
import { router } from "@/router";
import { apiMode } from "@/api/client";
import { DevToolbar } from "@/dev/DevToolbar";
import "./index.css";

const queryClient = new QueryClient();

async function enableMocking() {
  // "live": nothing is mocked, MSW never starts. "mock" and "hybrid" both need
  // the worker running — hybrid just has some routes passthrough() out of it
  // (see mocks/browser.ts, mocks/hybridPassthrough.ts).
  if (apiMode === "live") {
    return;
  }
  const { worker } = await import("../mocks/browser");
  return worker.start({ onUnhandledRequest: "warn" });
}

enableMocking().then(() => {
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
        <DevToolbar />
      </QueryClientProvider>
    </StrictMode>,
  );
});
