import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Outlet } from "react-router-dom";
import App from "./App";

const auth = vi.hoisted(() => ({ user: null as { role: string } | null, loading: false }));
vi.mock("./context/auth", () => ({
  useAuth: () => auth,
  canManageOperations: () => true,
  canManageUsers: () => true,
}));
vi.mock("./components/AppShell", () => ({
  AppShell: () => <div>Authenticated application<Outlet /></div>,
}));
vi.mock("./pages/DashboardPage", () => ({ DashboardPage: () => <div>Existing dashboard</div> }));

function renderApp(path = "/") {
  return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>);
}

describe("Public discovery routing", () => {
  beforeEach(() => { auth.user = null; auth.loading = false; });

  it("shows industry discovery for an anonymous homepage visitor", async () => {
    renderApp();
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("One Marine Industry.");
    expect(screen.queryByText("Authenticated application")).not.toBeInTheDocument();
  });

  it("preserves the authenticated dashboard and application shell", async () => {
    auth.user = { role: "owner" };
    renderApp();
    expect(await screen.findByText("Existing dashboard")).toBeInTheDocument();
    expect(screen.getByText("Authenticated application")).toBeInTheDocument();
  });

  it("keeps direct industry pages public", async () => {
    renderApp("/industries/recreational-fishing");
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Marine intelligence for recreational anglers");
  });
});
