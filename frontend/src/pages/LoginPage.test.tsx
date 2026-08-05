import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AuthProvider } from "../context/AuthContext";
import { LoginPage } from "./LoginPage";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function renderLoginPage() {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<div>Dashboard home</div>} />
        </Routes>
      </MemoryRouter>
    </AuthProvider>,
  );
}

const USER = {
  id: "11111111-1111-1111-1111-111111111111",
  company_id: "cccccccc-cccc-cccc-cccc-cccccccccccc",
  email: "owner@example.com",
  full_name: "Owner Person",
  role: "owner" as const,
  is_active: true,
};

describe("LoginPage", () => {
  beforeEach(() => {
    localStorage.clear();
    // No CSRF cookie set at test start -- AuthProvider's hydration effect
    // (see AuthContext.tsx) skips straight to "logged out" without firing
    // GET /auth/me, so tests only ever need to mock the routes they
    // actually exercise (POST /auth/login[, /auth/login/mfa]).
    document.cookie = "csrf_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("logs in directly and navigates home when the account has no MFA", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        user: USER,
        tokens: { access_token: "at-1", token_type: "bearer", expires_in: 900 },
      }),
    );

    renderLoginPage();

    await userEvent.type(screen.getByLabelText(/email/i), "owner@example.com");
    await userEvent.type(screen.getByLabelText(/password/i), "correct-horse-battery-staple");
    await userEvent.click(screen.getByRole("button", { name: /^log in$/i }));

    expect(await screen.findByText("Dashboard home")).toBeInTheDocument();
  });

  it("shows the two-factor prompt instead of navigating when MFA is required", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ mfa_required: true, pre_auth_token: "pre-auth-abc" }),
    );

    renderLoginPage();

    await userEvent.type(screen.getByLabelText(/email/i), "owner@example.com");
    await userEvent.type(screen.getByLabelText(/password/i), "correct-horse-battery-staple");
    await userEvent.click(screen.getByRole("button", { name: /^log in$/i }));

    expect(await screen.findByText("Two-factor verification")).toBeInTheDocument();
    // Still on the login screen, not the dashboard -- no tokens were issued.
    expect(screen.queryByText("Dashboard home")).not.toBeInTheDocument();
  });

  it("completes login after entering a correct second-factor code", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ mfa_required: true, pre_auth_token: "pre-auth-abc" }),
    );

    renderLoginPage();
    await userEvent.type(screen.getByLabelText(/email/i), "owner@example.com");
    await userEvent.type(screen.getByLabelText(/password/i), "correct-horse-battery-staple");
    await userEvent.click(screen.getByRole("button", { name: /^log in$/i }));
    await screen.findByText("Two-factor verification");

    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        user: USER,
        tokens: { access_token: "at-2", token_type: "bearer", expires_in: 900 },
      }),
    );
    await userEvent.type(screen.getByLabelText(/authentication code/i), "123456");
    await userEvent.click(screen.getByRole("button", { name: /verify and log in/i }));

    expect(await screen.findByText("Dashboard home")).toBeInTheDocument();
    const lastCall = fetchMock.mock.calls.at(-1);
    expect(String(lastCall?.[0])).toMatch(/\/auth\/login\/mfa$/);
    expect(JSON.parse(String(lastCall?.[1]?.body))).toEqual({
      pre_auth_token: "pre-auth-abc",
      code: "123456",
    });
  });

  it("shows an error and stays on the code prompt when the second factor is wrong", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ mfa_required: true, pre_auth_token: "pre-auth-abc" }),
    );

    renderLoginPage();
    await userEvent.type(screen.getByLabelText(/email/i), "owner@example.com");
    await userEvent.type(screen.getByLabelText(/password/i), "correct-horse-battery-staple");
    await userEvent.click(screen.getByRole("button", { name: /^log in$/i }));
    await screen.findByText("Two-factor verification");

    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "invalid code" }, 401));
    await userEvent.type(screen.getByLabelText(/authentication code/i), "000000");
    await userEvent.click(screen.getByRole("button", { name: /verify and log in/i }));

    expect(await screen.findByText(/invalid code|unable to verify/i)).toBeInTheDocument();
    expect(screen.getByText("Two-factor verification")).toBeInTheDocument();
  });

  it("lets the user go back to the credentials form from the code prompt", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ mfa_required: true, pre_auth_token: "pre-auth-abc" }),
    );

    renderLoginPage();
    await userEvent.type(screen.getByLabelText(/email/i), "owner@example.com");
    await userEvent.type(screen.getByLabelText(/password/i), "correct-horse-battery-staple");
    await userEvent.click(screen.getByRole("button", { name: /^log in$/i }));
    await screen.findByText("Two-factor verification");

    await userEvent.click(screen.getByRole("button", { name: /back to login/i }));

    expect(screen.getByText("Log in to HarborIQ")).toBeInTheDocument();
  });
});
