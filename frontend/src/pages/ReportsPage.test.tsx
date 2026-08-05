import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setAccessToken, setRefreshToken } from "../lib/tokenStore";
import { ReportsPage } from "./ReportsPage";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function csvResponse(body: string) {
  return new Response(body, {
    status: 200,
    headers: {
      "content-type": "text/csv",
      "content-disposition": 'attachment; filename="pnl.csv"',
    },
  });
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ReportsPage />
    </QueryClientProvider>,
  );
}

const pnlBody = {
  start_date: "2026-01-01T00:00:00Z",
  end_date: "2026-08-01T00:00:00Z",
  months: [
    {
      month: "2026-07",
      revenue: "500.00",
      refunds: "0.00",
      net_revenue: "500.00",
      parts_cost: "50.00",
      labor_cost: "100.00",
      labor_cost_unavailable: false,
      unrated_technicians: [],
      net: "350.00",
    },
  ],
  totals: {
    revenue: "500.00",
    refunds: "0.00",
    net_revenue: "500.00",
    parts_cost: "50.00",
    labor_cost: "100.00",
    labor_cost_unavailable: false,
    unrated_technicians: [],
    net: "350.00",
  },
};

const cashFlowBody = {
  start_date: "2026-01-01T00:00:00Z",
  end_date: "2026-08-01T00:00:00Z",
  months: [
    {
      month: "2026-07",
      cash_in: "500.00",
      refunds_out: "0.00",
      cost_incurred: "50.00",
      net_cash: "450.00",
    },
  ],
  totals: { cash_in: "500.00", refunds_out: "0.00", cost_incurred: "50.00", net_cash: "450.00" },
  cost_incurred_caveat:
    "Cost incurred reflects purchase orders received in this period, not necessarily cash paid to vendors.",
};

describe("ReportsPage", () => {
  beforeEach(() => {
    localStorage.clear();
    setAccessToken("access-token");
    setRefreshToken("refresh-token");
    vi.stubGlobal("fetch", vi.fn());
    URL.createObjectURL = vi.fn(() => "blob:mock");
    URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("renders the P&L tab by default with totals and monthly rows", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse(pnlBody));

    renderPage();

    expect(await screen.findByText("Profit & loss")).toBeInTheDocument();
    expect(await screen.findByText("2026-07")).toBeInTheDocument();
    expect(screen.getAllByText("$500.00").length).toBeGreaterThan(0);
  });

  it("shows the unrated technicians warning banner when labor cost is unavailable", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        ...pnlBody,
        totals: { ...pnlBody.totals, labor_cost_unavailable: true, unrated_technicians: ["Jane Tech"] },
      }),
    );

    renderPage();

    expect(await screen.findByText(/Labor cost is incomplete/)).toBeInTheDocument();
    expect(screen.getByText(/Jane Tech/)).toBeInTheDocument();
  });

  it("switches to the cash flow tab and shows the cost-incurred caveat", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse(pnlBody));
    fetchMock.mockResolvedValueOnce(jsonResponse(cashFlowBody));

    renderPage();
    await screen.findByText("Profit & loss");

    fireEvent.click(screen.getByText("Cash flow"));

    expect(await screen.findByText(/purchase orders received in this period/)).toBeInTheDocument();
    expect(screen.getAllByText("$450.00").length).toBeGreaterThan(0);
  });

  it("triggers a CSV download when the export button is clicked", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse(pnlBody));
    fetchMock.mockResolvedValueOnce(csvResponse("month,revenue\n2026-07,500.00\n"));

    renderPage();
    await screen.findByText("Profit & loss");

    fireEvent.click(screen.getByText("Export CSV"));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/reports/pnl/export.csv"),
        expect.objectContaining({ method: "GET" }),
      );
    });
  });
});
