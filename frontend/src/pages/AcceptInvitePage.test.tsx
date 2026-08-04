import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "../context/AuthContext";
import { AcceptInvitePage } from "./AcceptInvitePage";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function renderAtToken(token: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <MemoryRouter initialEntries={[`/accept-invite/${token}`]}>
          <Routes>
            <Route path="/accept-invite/:token" element={<AcceptInvitePage />} />
            <Route path="/" element={<div>Dashboard home</div>} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe("AcceptInvitePage", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows the invite preview (company, role, email) once loaded", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        email: "newhire@example.com",
        role: "technician",
        full_name: null,
        company_name: "Off the Hook Marine",
      }),
    );

    renderAtToken("good-token");

    expect(await screen.findByText(/Off the Hook Marine/)).toBeInTheDocument();
    expect(screen.getByText(/newhire@example.com/)).toBeInTheDocument();
  });

  it("shows an invalid-link message on a 404 preview", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "invite not found" }, 404));

    renderAtToken("dead-token");

    expect(await screen.findByText(/invalid, expired, or has already been used/)).toBeInTheDocument();
  });

  it("gates submission on the 12-character password minimum via HTML5 constraint validation", async () => {
    // jsdom does not implement minlength constraint enforcement (form.submit()
    // / requestSubmit() don't block on it the way a real browser does), so
    // this asserts the contract the real browser enforces — the attribute is
    // present and wired to the live password state — rather than relying on
    // jsdom's incomplete validityState behaviour. The actual gating is
    // covered end-to-end by the manual smoke test and by the backend's own
    // `WeakPassword` → 422 rejection (see tests/test_auth_invites.py::
    // test_accept_rejects_a_weak_password).
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        email: "newhire@example.com",
        role: "office",
        full_name: null,
        company_name: "Off the Hook Marine",
      }),
    );

    renderAtToken("good-token");
    await screen.findByText(/Off the Hook Marine/);

    const user = userEvent.setup();
    const passwordInput = screen.getByLabelText(/Password/i);
    await user.type(passwordInput, "short");
    expect(passwordInput).toHaveAttribute("minlength", "12");
    expect(passwordInput).toHaveAttribute("required");
    expect(passwordInput).toHaveValue("short");
  });

  it("accepts the invite, logs the user in, and redirects to the dashboard", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({
          email: "newhire@example.com",
          role: "technician",
          full_name: null,
          company_name: "Off the Hook Marine",
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          user: {
            id: "u1",
            company_id: "c1",
            email: "newhire@example.com",
            full_name: "New Hire",
            role: "technician",
            is_active: true,
          },
          tokens: {
            access_token: "tok",
            refresh_token: "refresh",
            token_type: "bearer",
            expires_in: 900,
          },
        }),
      );

    renderAtToken("good-token");
    await screen.findByText(/Off the Hook Marine/);

    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/Password/i), "correct horse battery staple");
    await user.click(screen.getByRole("button", { name: /accept invite/i }));

    await waitFor(() => expect(screen.getByText("Dashboard home")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const acceptCall = fetchMock.mock.calls[1];
    expect(String(acceptCall[0])).toContain("/auth/invites/good-token/accept");
  });

  it("surfaces a server-side error (e.g. reused token) without crashing", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({
          email: "newhire@example.com",
          role: "technician",
          full_name: null,
          company_name: "Off the Hook Marine",
        }),
      )
      .mockResolvedValueOnce(jsonResponse({ detail: "invite has already been used" }, 404));

    renderAtToken("good-token");
    await screen.findByText(/Off the Hook Marine/);

    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/Password/i), "correct horse battery staple");
    await user.click(screen.getByRole("button", { name: /accept invite/i }));

    expect(await screen.findByText(/invite has already been used/)).toBeInTheDocument();
  });
});
