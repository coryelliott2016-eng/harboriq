import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setAccessToken } from "../lib/tokenStore";
import { BillingSettingsPage } from "./BillingSettingsPage";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <BillingSettingsPage />
    </QueryClientProvider>,
  );
}

describe("BillingSettingsPage", () => {
  beforeEach(() => {
    localStorage.clear();
    setAccessToken("access-token");
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows 'Not connected' and a Connect Stripe button when no account is onboarded", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ connected: false, account_id: null, charges_enabled: false, details_submitted: false }),
    );

    renderPage();

    expect(await screen.findByText("Not connected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /connect stripe/i })).toBeInTheDocument();
  });

  it("shows 'Connected' once charges are enabled", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ connected: true, account_id: "acct_123", charges_enabled: true, details_submitted: true }),
    );

    renderPage();

    expect(await screen.findByText("Connected")).toBeInTheDocument();
    expect(screen.getByText(/acct_123/)).toBeInTheDocument();
  });

  it("redirects the browser to the onboarding URL when Connect Stripe is clicked", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ connected: false, account_id: null, charges_enabled: false, details_submitted: false }),
    );
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ account_id: "acct_123", onboarding_url: "https://connect.stripe.com/setup/acct_123" }),
    );

    // jsdom does not implement navigation; stub location.href assignment.
    delete (window as unknown as { location?: unknown }).location;
    (window as unknown as { location: { href: string } }).location = { href: "" };

    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /connect stripe/i }));

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const [url, options] = fetchMock.mock.calls[1];
    expect(String(url)).toContain("/billing/connect/onboarding-link");
    expect(options.method).toBe("POST");
    expect(window.location.href).toBe("https://connect.stripe.com/setup/acct_123");
  });

  it("runs the dunning sweep and shows the reminded count", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ connected: false, account_id: null, charges_enabled: false, details_submitted: false }),
    );
    fetchMock.mockResolvedValueOnce(jsonResponse({ reminded_invoice_ids: ["inv-1", "inv-2"], count: 2 }));

    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /run dunning sweep now/i }));

    expect(await screen.findByText(/Reminded 2 overdue invoices/)).toBeInTheDocument();
  });
});
