import { useRouteError } from "react-router-dom";
import { ErrorState } from "./primitives/ErrorState";

/**
 * React Router's per-route error boundary — Task 2 fallout, not Task 2
 * itself. The live-path validation relief valve hands back an unvalidated
 * payload instead of throwing, so a screen isn't torn down by a bad zod
 * parse — but a component that still assumes the full shape unconditionally
 * (e.g. `policy.insurer.name`) can throw a plain JS TypeError during render
 * when a live response is genuinely missing a field. safeParse can't prevent
 * that; only a route-level boundary stops it from replacing the whole page
 * with React Router's raw dev stack-trace screen. Reuses <ErrorState> so a
 * crashed screen still reads as part of the product. Attached per leaf route
 * (see router.tsx), not on the AppShell route itself, so the nav shell keeps
 * rendering around the crashed screen instead of disappearing with it.
 */
export function RouteErrorFallback() {
  const error = useRouteError();

  if (import.meta.env.DEV) {
    console.error("[route-error-boundary] a screen crashed while rendering:", error);
  }

  return (
    <ErrorState
      message="This screen couldn't render — likely a response shape the UI didn't expect. Check the dev toolbar for validation issues, or try reloading."
      onRetry={() => window.location.reload()}
    />
  );
}
