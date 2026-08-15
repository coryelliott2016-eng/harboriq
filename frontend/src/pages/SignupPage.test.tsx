import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AuthProvider } from "../context/AuthContext";
import { SignupPage } from "./SignupPage";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function renderSignupPage() {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={["/signup"]}>
        <Routes>
          <Route path="/signup" element={<SignupPage />} />
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

describe("SignupPage", () => {
  beforeEach(() => {
    localStorage.clear();
    document.cookie = "csrf_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("blocks submission and never calls the API until the terms checkbox is checked", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;

    renderSignupPage();

    await userEvent.type(screen.getByLabelText(/company name/i), "Acme Marine");
    await userEvent.type(screen.getByLabelText(/^email$/i), "owner@example.com");
    await userEvent.type(screen.getByLabelText(/^password$/i), "correct-horse-battery-staple");

    // The submit button is disabled until the terms checkbox is checked.
    expect(screen.getByRole("button", { name: /create account/i })).toBeDisabled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("links out to the marketing site's Terms of Service and Privacy Policy pages", () => {
    renderSignupPage();

    expect(screen.getByRole("link", { name: /terms of service/i })).toHaveAttribute(
      "href",
      "https://harboriq.com/#/terms",
    );
    expect(screen.getByRole("link", { name: /privacy policy/i })).toHaveAttribute(
      "href",
      "https://harboriq.com/#/privacy",
    );
  });

  it("signs up and navigates home once the terms checkbox is checked", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        user: USER,
        tokens: { access_token: "at-1", token_type: "bearer", expires_in: 900 },
      }),
    );

    renderSignupPage();

    await userEvent.type(screen.getByLabelText(/company name/i), "Acme Marine");
    await userEvent.type(screen.getByLabelText(/^email$/i), "owner@example.com");
    await userEvent.type(screen.getByLabelText(/^password$/i), "correct-horse-battery-staple");
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: /create account/i }));

    expect(await screen.findByText("Dashboard home")).toBeInTheDocument();
  });
});
