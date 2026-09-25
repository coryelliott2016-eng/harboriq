import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setAccessToken } from "../lib/tokenStore";
import { JobEstimates } from "./JobEstimates";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const baseEstimate = {
  id: "est-1",
  company_id: "company-1",
  job_id: "job-1",
  customer_id: "cust-1",
  currency: "USD",
  subtotal: "380.00",
  tax_rate: "0.0700",
  tax_total: "3.50",
  total: "383.50",
  notes: null,
  sent_at: null,
  approved_at: null,
  created_at: "2026-09-22T00:00:00Z",
  updated_at: "2026-09-22T00:00:00Z",
};

function renderPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/jobs/job-1"]}>
        <Routes>
          <Route path="/jobs/:id" element={<JobEstimates jobId="job-1" />} />
          <Route path="/invoices/:id" element={<div>Invoice page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("JobEstimates", () => {
  beforeEach(() => {
    localStorage.clear();
    setAccessToken("access-token");
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows an empty state when the job has no estimates", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse([]));
    renderPanel();
    expect(await screen.findByText(/No estimates yet/)).toBeInTheDocument();
  });

  it("sends a draft estimate and confirms the portal email", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock
      .mockResolvedValueOnce(jsonResponse([{ ...baseEstimate, status: "draft" }]))
      .mockResolvedValueOnce(
        jsonResponse({ estimate: { ...baseEstimate, status: "sent" }, email_queued: true }),
      )
      .mockResolvedValue(jsonResponse([{ ...baseEstimate, status: "sent" }]));

    renderPanel();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /send to customer/i }));

    expect(await screen.findByText(/emailed a portal link/)).toBeInTheDocument();
    const sendCall = fetchMock.mock.calls.find(([url]) => String(url).includes("/estimates/est-1/send"));
    expect(sendCall).toBeDefined();
    expect((sendCall![1] as RequestInit).method).toBe("POST");
  });

  it("converts an approved estimate and navigates to the invoice", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock
      .mockResolvedValueOnce(jsonResponse([{ ...baseEstimate, status: "approved" }]))
      .mockResolvedValueOnce(
        jsonResponse({ estimate: { ...baseEstimate, status: "invoiced" }, invoice_id: "inv-9" }),
      )
      .mockResolvedValue(jsonResponse([]));

    renderPanel();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /convert to invoice/i }));
    expect(await screen.findByText("Invoice page")).toBeInTheDocument();
  });

  it("creates an estimate with a diagnostic fee line and converts tax percent to a rate", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse({ ...baseEstimate, status: "draft", line_items: [], invoice_id: null }, 201))
      .mockResolvedValue(jsonResponse([{ ...baseEstimate, status: "draft" }]));

    renderPanel();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /new estimate/i }));

    const descriptions = screen.getAllByLabelText(/^Description$/);
    await user.type(descriptions[0], "Replace impeller");
    await user.click(screen.getByRole("button", { name: /add diagnostic fee/i }));
    const tax = screen.getByLabelText(/Tax rate/);
    await user.clear(tax);
    await user.type(tax, "7");
    await user.click(screen.getByRole("button", { name: /create draft estimate/i }));

    await waitFor(() => {
      const createCall = fetchMock.mock.calls.find(
        ([url, init]) => String(url).endsWith("/estimates") && (init as RequestInit)?.method === "POST",
      );
      expect(createCall).toBeDefined();
      const body = JSON.parse(String((createCall![1] as RequestInit).body));
      expect(body.job_id).toBe("job-1");
      expect(body.tax_rate).toBe("0.0700");
      expect(body.line_items).toHaveLength(2);
      expect(body.line_items[1]).toMatchObject({ kind: "fee", description: "Diagnostic fee" });
    });
    expect(await screen.findByText(/Draft estimate created/)).toBeInTheDocument();
  });

  it("shows a server error when conversion is rejected", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock
      .mockResolvedValueOnce(jsonResponse([{ ...baseEstimate, status: "approved" }]))
      .mockResolvedValueOnce(jsonResponse({ detail: "Illegal transition" }, 409));

    renderPanel();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /convert to invoice/i }));
    expect(await screen.findByText(/Illegal transition/)).toBeInTheDocument();
  });
});
