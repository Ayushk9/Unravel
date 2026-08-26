import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { Menu, X } from "lucide-react";

const NAV_ITEMS = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/policies", label: "Policies" },
  { to: "/claims", label: "Claims" },
  { to: "/alerts", label: "Alerts" },
  { to: "/insurers", label: "Insurers" },
  { to: "/settings", label: "Settings" },
];

function navLinkClasses({ isActive }: { isActive: boolean }) {
  return `rounded px-2 py-1.5 text-sm font-medium transition-colors ${
    isActive ? "bg-secondary text-foreground" : "text-ink-muted hover:text-foreground"
  }`;
}

/** Nav + layout shell. Responsive: horizontal nav >=768px, collapsible menu below it. */
export function AppShell() {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-rule bg-card">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <NavLink to="/" className="font-serif text-lg font-semibold text-foreground">
            Unravel
          </NavLink>

          <nav aria-label="Primary" className="hidden items-center gap-1 md:flex">
            {NAV_ITEMS.map((item) => (
              <NavLink key={item.to} to={item.to} className={navLinkClasses}>
                {item.label}
              </NavLink>
            ))}
          </nav>

          <button
            type="button"
            className="rounded p-1.5 text-ink-muted hover:text-foreground md:hidden"
            aria-label={menuOpen ? "Close menu" : "Open menu"}
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((open) => !open)}
          >
            {menuOpen ? <X className="size-5" aria-hidden="true" /> : <Menu className="size-5" aria-hidden="true" />}
          </button>
        </div>

        {menuOpen && (
          <nav aria-label="Primary" className="flex flex-col gap-1 border-t border-rule px-4 py-3 md:hidden">
            {NAV_ITEMS.map((item) => (
              <NavLink key={item.to} to={item.to} className={navLinkClasses} onClick={() => setMenuOpen(false)}>
                {item.label}
              </NavLink>
            ))}
          </nav>
        )}
      </header>

      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-6 sm:px-6">
        <Outlet />
      </main>
    </div>
  );
}
