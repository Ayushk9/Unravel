import { createBrowserRouter, type RouteObject } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { RouteErrorFallback } from "@/components/RouteErrorFallback";
import { PlaceholderScreen } from "@/pages/PlaceholderScreen";
import { KitchenSink } from "@/pages/KitchenSink";
import { Dashboard } from "@/pages/Dashboard";
import { PolicyList } from "@/pages/PolicyList";
import { PolicyUpload } from "@/pages/PolicyUpload";
import { PolicyDetail } from "@/pages/PolicyDetail";
import { PolicyAsk } from "@/pages/PolicyAsk";
import { ClaimList } from "@/pages/ClaimList";
import { ClaimNew } from "@/pages/ClaimNew";
import { ClaimWorkspace } from "@/pages/ClaimWorkspace";
import { Alerts } from "@/pages/Alerts";
import { Settings } from "@/pages/Settings";

/**
 * Route table from docs/claude-code-frontend-prompt.md §6. Screens not built
 * yet render PlaceholderScreen rather than nothing, so nav + responsive
 * layout have somewhere real to exercise before the features land.
 */
/**
 * Every leaf route gets the same errorElement (see RouteErrorFallback) — a
 * screen crashing at render time degrades to a friendly message inside the
 * AppShell's nav frame, not React Router's raw stack-trace screen. Applied
 * via .map() so a new route can't accidentally be added without one.
 */
const appShellChildren: RouteObject[] = [
  { index: true, element: <PlaceholderScreen title="Sign in" phase="a later phase" /> },
  { path: "dashboard", element: <Dashboard /> },
  { path: "policies", element: <PolicyList /> },
  { path: "policies/upload", element: <PolicyUpload /> },
  { path: "policies/:id", element: <PolicyDetail /> },
  { path: "policies/:id/ask", element: <PolicyAsk /> },
  { path: "claims", element: <ClaimList /> },
  { path: "claims/new", element: <ClaimNew /> },
  { path: "claims/:id", element: <ClaimWorkspace /> },
  { path: "claims/:id/grievance", element: <PlaceholderScreen title="Grievance drafting" phase="Phase 5" /> },
  { path: "alerts", element: <Alerts /> },
  { path: "insurers", element: <PlaceholderScreen title="Insurer benchmarking" phase="Phase 6" /> },
  { path: "settings", element: <Settings /> },
  { path: "*", element: <PlaceholderScreen title="Page not found" phase="—" /> },
].map((route) => ({ ...route, errorElement: <RouteErrorFallback /> }));

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    errorElement: <RouteErrorFallback />,
    children: appShellChildren,
  },
  {
    path: "/kitchen-sink",
    element: <KitchenSink />,
    errorElement: <RouteErrorFallback />,
  },
]);
