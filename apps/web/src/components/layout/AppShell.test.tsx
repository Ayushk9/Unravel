// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { appShellChildren } from "@/router";
import { AppShell } from "./AppShell";

/**
 * Nothing the panel can reach says "not built yet" or names a later phase:
 * "/" and "/sign-in" land on the dashboard, the nav has no link to a screen
 * that isn't part of this version, and the header says whose data this is.
 * The dashboard is stubbed: only where the app lands is under test here.
 */

vi.mock("@/pages/Dashboard", () => ({ Dashboard: () => <h1>Dashboard screen</h1> }));
vi.mock("@/components/primitives/DocumentViewer", () => ({ DocumentViewer: () => null }));

function renderAt(path: string) {
  const router = createMemoryRouter([{ path: "/", element: <AppShell />, children: appShellChildren }], { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
}

afterEach(cleanup);

describe("AppShell and the route table", () => {
  it.each(["/", "/sign-in"])("%s goes to the dashboard", async (path) => {
    const router = renderAt(path);
    expect(await screen.findByText("Dashboard screen")).toBeTruthy();
    expect(router.state.location.pathname).toBe("/dashboard");
  });

  it("names the demo household in the header", async () => {
    renderAt("/dashboard");
    expect(await screen.findByText("Demo household: Rao household")).toBeTruthy();
  });

  it("has no nav link to insurer benchmarking", async () => {
    renderAt("/dashboard");
    await screen.findByText("Dashboard screen");
    expect(screen.queryByRole("link", { name: "Insurers" })).toBeNull();
  });

  it.each(["/insurers", "/no-such-page"])("%s says plainly what is there, with no phase wording", async (path) => {
    renderAt(path);
    await screen.findByRole("heading");
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/not built yet|later phase|phase \d/i);
  });

  it("states that benchmarking is not part of this version", async () => {
    renderAt("/insurers");
    expect(await screen.findByText("Planned: insurer benchmarking (not part of this version).")).toBeTruthy();
  });
});
