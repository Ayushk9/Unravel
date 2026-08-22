import { createBrowserRouter } from "react-router-dom";
import App from "@/App";

/**
 * Route table grows through Phases 3–6 per docs/claude-code-frontend-prompt.md
 * §6. Phase 0 only needs the data router itself wired up.
 */
export const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
  },
]);
