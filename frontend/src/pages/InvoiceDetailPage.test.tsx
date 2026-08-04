import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setAccessToken, setRefreshToken } from "../lib/tokenStore";
import { InvoiceDetailPage } from "./InvoiceDetailPage";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const baseInvoice = {
  id: "11111111-2222-3333-4444-555555555555",
  company_id: "company-1",
  estimate_id: null,
  customer_id: "cust-1",
  currency: "usd",
  subtotal: "100.00",
  tax_total: "0.00",
  tax_rate: "0",
  total: "100.00",
  due_date: null,
  sent_at: "2026-08-01T00:00:00Z",
  paid_at: null,
  voided_at: null,
  stripe_payment_intent_id: null,
  stripe_checkout_session_id: null,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
  line_items: [],
};

function renderAtInvoice(id: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/invoices/${id}`]}>
        <Routes>
          <Route path="/invoices/:id" element={<InvoiceDetailPage />} />
          <Route path="/invoices" element={<div>All invoices</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("InvoiceDetailPage — refunds (Phase 8)", () => {
  beforeEach(() => {
    localStorage.clear();
    setAccessToken("access-token");
    setRefreshToken("refresh-token");
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows a Refund button for a paid invoice and defaults the amount to amount_paid", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ ...baseInvoice, status: "paid", amount_paid: "100.00", balance_due: "0.00" }),
    );

    renderAtInvoice(baseInvoice.id);

    const refundButton = await screen.findByRole("button", { name: /^refund$/i });
    const user = userEvent.setup();
    await user.click(refundButton);

    expect(screen.getByText(/Issue a refund/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Amount \(USD\)/i)).toHaveValue(100);
  });

  it("does not show a Refund button for a draft invoice", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ ...baseInvoice, status: "draft", amount_paid: "0.00", balance_due: "100.00" }),
    );

    renderAtInvoice(baseInvoice.id);

    await screen.findByText(/Invoice/);
    expect(screen.queryByRole("button", { name: /^refund$/i })).not.toBeInTheDocument();
  });

  it("submits a partial refund and shows the success notice", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ ...baseInvoice, status: "paid", amount_paid: "100.00", balance_due: "0.00" }),
    );
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        invoice: { ...baseInvoice, status: "partially_refunded", amount_paid: "100.00", balance_due: "0.00" },
        refund: {
          id: "ref-1",
          invoice_id: baseInvoice.id,
          amount: "40.00",
          reason: "customer request",
          stripe_refund_id: "re_123",
          created_at: "2026-08-04T00:00:00Z",
        },
      }),
    );
    // `invalidateQueries({ queryKey: ["invoices"] })` is a prefix match that
    // also covers `["invoices", id]`, so both invalidated queries refetch.
    // A `Response` body can only be read once, so a shared `mockResolvedValue`
    // instance would make the second refetch's `.json()` fail silently (the
    // client swallows that into `null` -- see api.ts's `.catch(() => null)`).
    // Build a fresh Response per call instead.
    fetchMock.mockImplementation(() =>
      Promise.resolve(
        jsonResponse({ ...baseInvoice, status: "partially_refunded", amount_paid: "100.00", balance_due: "0.00" }),
      ),
    );

    renderAtInvoice(baseInvoice.id);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /^refund$/i }));
    const amountInput = screen.getByLabelText(/Amount \(USD\)/i);
    await user.clear(amountInput);
    await user.type(amountInput, "40.00");
    await user.type(screen.getByLabelText(/Reason/i), "customer request");
    await user.click(screen.getByRole("button", { name: /confirm refund/i }));

    expect(await screen.findByText(/Refunded \$40\.00/)).toBeInTheDocument();

    const [, options] = fetchMock.mock.calls[1];
    // A number input normalizes "40.00" -> "40" once typed/read back, so the
    // amount sent is "40" here -- amount formatting/precision is enforced
    // server-side (see app/schemas/invoices.py::RefundRequest), not by this
    // form control.
    expect(JSON.parse(options.body)).toEqual({ amount: "40", reason: "customer request" });
  });
});
