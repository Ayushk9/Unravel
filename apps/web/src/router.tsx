import { createBrowserRouter } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { PlaceholderScreen } from "@/pages/PlaceholderScreen";
import { KitchenSink } from "@/pages/KitchenSink";

/**
 * Route table from docs/claude-code-frontend-prompt.md §6. Screens not built
 * yet render PlaceholderScreen rather than nothing, so nav + responsive
 * layout have somewhere real to exercise before the features land.
 */
export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <PlaceholderScreen title="Sign in" phase="Phase 3" /> },
      { path: "dashboard", element: <PlaceholderScreen title="Household dashboard" phase="Phase 3" /> },
      { path: "policies", element: <PlaceholderScreen title="Policy list" phase="Phase 3" /> },
      { path: "policies/upload", element: <PlaceholderScreen title="Upload a policy" phase="Phase 3" /> },
      { path: "policies/:id", element: <PlaceholderScreen title="Policy detail" phase="Phase 3" /> },
      { path: "policies/:id/ask", element: <PlaceholderScreen title="Ask about your policy" phase="Phase 3" /> },
      { path: "claims", element: <PlaceholderScreen title="Claims" phase="Phase 4" /> },
      { path: "claims/new", element: <PlaceholderScreen title="File a claim" phase="Phase 4" /> },
      { path: "claims/:id", element: <PlaceholderScreen title="Claim workspace" phase="Phase 4" /> },
      { path: "claims/:id/grievance", element: <PlaceholderScreen title="Grievance drafting" phase="Phase 5" /> },
      { path: "alerts", element: <PlaceholderScreen title="Alerts" phase="Phase 6" /> },
      { path: "insurers", element: <PlaceholderScreen title="Insurer benchmarking" phase="Phase 6" /> },
      { path: "settings", element: <PlaceholderScreen title="Settings" phase="a later phase" /> },
      { path: "*", element: <PlaceholderScreen title="Page not found" phase="—" /> },
    ],
  },
  {
    path: "/kitchen-sink",
    element: <KitchenSink />,
  },
]);
