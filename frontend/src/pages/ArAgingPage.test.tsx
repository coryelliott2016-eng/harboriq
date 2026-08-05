import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setAccessToken } from "../lib/tokenStore";
import { ArAgingPage } from "./ArAgingPage";

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
      <ArAgingPage />
    </QueryClientProvider>,
  );
}

describe("ArAgingPage", () => {
  beforeEach(() => {
    localStorage.clear();
    setAccessToken("access-token");
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("renders bucket totals and the per-customer table", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        as_of: "2026-08-04T12:00:00Z",
        customers: [
          {
            customer_id: "cust-1",
            customer_name: "Dana Reyes",
            buckets: { current: "0.00", days_1_30: "150.00", days_31_60: "0.00", days_61_90: "0.00", days_90_plus: "0.00" },
            total: "150.00",
            invoice_count: 1,
          },
        ],
        bucket_totals: { current: "0.00", days_1_30: "150.00", days_31_60: "0.00", days_61_90: "0.00", days_90_plus: "0.00" },
        grand_total: "150.00",
      }),
    );

    renderPage();

    expect(await screen.findByText("Dana Reyes")).toBeInTheDocument();
    expect(screen.getAllByText("$150.00").length).toBeGreaterThan(0);
    expect(screen.getByText(/Grand total outstanding/)).toBeInTheDocument();
  });

  it("shows an empty state when nothing is outstanding", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        as_of: "2026-08-04T12:00:00Z",
        customers: [],
        bucket_totals: { current: "0.00", days_1_30: "0.00", days_31_60: "0.00", days_61_90: "0.00", days_90_plus: "0.00" },
        grand_total: "0.00",
      }),
    );

    renderPage();

    expect(await screen.findByText(/No outstanding balances/)).toBeInTheDocument();
  });
});
