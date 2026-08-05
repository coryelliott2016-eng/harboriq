import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setAccessToken } from "./tokenStore";
import { billingApi, invoicesApi, reportsApi } from "./services";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

// Light coverage for the Phase 8 API client additions (Stripe Connect,
// refunds, dunning, AR aging) -- follows the same "hit the client, assert
// URL/method/payload" style as services.dispatch.test.ts.
describe("Phase 8 API client additions", () => {
  beforeEach(() => {
    localStorage.clear();
    setAccessToken("access-token");
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("posts an onboarding link request and returns the redirect URL", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ account_id: "acct_123", onboarding_url: "https://connect.stripe.com/setup/acct_123" }),
    );

    const result = await billingApi.connectOnboardingLink();

    expect(result.onboarding_url).toContain("connect.stripe.com");
    const [url, options] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/billing/connect/onboarding-link");
    expect(options.method).toBe("POST");
  });

  it("fetches Stripe Connect status", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ connected: true, account_id: "acct_123", charges_enabled: true, details_submitted: true }),
    );

    const status = await billingApi.connectStatus();

    expect(status.connected).toBe(true);
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/billing/connect/status");
  });

  it("triggers a dunning sweep and returns the reminded count", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ reminded_invoice_ids: ["inv-1", "inv-2"], count: 2 }),
    );

    const result = await billingApi.runDunning();

    expect(result.count).toBe(2);
    const [url, options] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/billing/dunning/run");
    expect(options.method).toBe("POST");
  });

  it("fetches the AR aging report", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        as_of: "2026-08-04T00:00:00Z",
        customers: [],
        bucket_totals: { current: "0", days_1_30: "0", days_31_60: "0", days_61_90: "0", days_90_plus: "0" },
        grand_total: "0",
      }),
    );

    const report = await reportsApi.arAging();

    expect(report.grand_total).toBe("0");
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/reports/ar-aging");
  });

  it("posts a refund with amount and reason", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        invoice: { id: "inv-1", status: "partially_refunded" },
        refund: { id: "ref-1", invoice_id: "inv-1", amount: "40.00", reason: "customer request", stripe_refund_id: "re_123", created_at: "2026-08-04T00:00:00Z" },
      }),
    );

    const result = await invoicesApi.refund("inv-1", { amount: "40.00", reason: "customer request" });

    expect(result.refund.amount).toBe("40.00");
    const [url, options] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/invoices/inv-1/refund");
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body)).toEqual({ amount: "40.00", reason: "customer request" });
  });

  it("posts an empty body for a full refund when no amount is given", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        invoice: { id: "inv-1", status: "refunded" },
        refund: { id: "ref-1", invoice_id: "inv-1", amount: "100.00", reason: null, stripe_refund_id: "re_123", created_at: "2026-08-04T00:00:00Z" },
      }),
    );

    await invoicesApi.refund("inv-1");

    const [, options] = fetchMock.mock.calls[0];
    expect(JSON.parse(options.body)).toEqual({});
  });
});
