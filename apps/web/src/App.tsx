import { useHealthCheck } from "@/api/endpoints/health";

/**
 * Phase 0 placeholder shell. Layout, navigation, and the design-system
 * primitives that will replace this page arrive in Phase 1.
 */
function App() {
  const health = useHealthCheck();

  return (
    <main className="mx-auto flex min-h-screen max-w-prose flex-col justify-center gap-4 px-6">
      <p className="font-mono text-xs tracking-wide text-muted-foreground uppercase">
        Phase 0 — scaffold
      </p>
      <h1 className="font-serif text-3xl text-foreground">PolicyClear</h1>
      <p className="text-base text-muted-foreground">
        Frontend integration harness. The backend does not exist yet — every screen
        runs against mock data until <code className="font-mono text-sm">VITE_API_MODE=live</code> points
        at a real API.
      </p>
      <div className="rounded border border-border bg-card px-4 py-3 font-mono text-sm">
        {health.isPending && <span className="text-muted-foreground">Checking API…</span>}
        {health.isError && <span className="text-destructive">API unreachable</span>}
        {health.isSuccess && (
          <span className="text-primary">MSW health check: {health.data.status}</span>
        )}
      </div>
    </main>
  );
}

export default App;
