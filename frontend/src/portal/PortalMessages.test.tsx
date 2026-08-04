import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PortalMessages } from "./PortalMessages";

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
      <MemoryRouter initialEntries={[`/portal/${token}/messages`]}>
        <Routes>
          <Route path="/portal/:token/messages" element={<PortalMessages />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PortalMessages", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("lists existing messages and sends a new one", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse([
          {
            id: "m1",
            company_id: "co1",
            customer_id: "cust-1",
            job_id: null,
            sender_type: "staff",
            sender_user_id: "u1",
            body: "Your boat is ready for pickup.",
            created_at: "2026-01-01T12:00:00Z",
            read_at: null,
          },
        ]),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          id: "m2",
          company_id: "co1",
          customer_id: "cust-1",
          job_id: null,
          sender_type: "customer",
          sender_user_id: null,
          body: "Thank you!",
          created_at: "2026-01-01T12:05:00Z",
          read_at: null,
        }),
      );

    renderAtToken("good-token");

    expect(await screen.findByText("Your boat is ready for pickup.")).toBeInTheDocument();

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Message"), "Thank you!");
    await user.click(screen.getByRole("button", { name: /send/i }));

    const [url, options] = fetchMock.mock.calls[1];
    expect(String(url)).toContain("/portal/good-token/messages");
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body)).toEqual({ body: "Thank you!", job_id: undefined });
  });

  it("shows an invalid-link message on a 404", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "not found" }, 404));

    renderAtToken("dead-token");

    expect(await screen.findByText(/invalid or has expired/)).toBeInTheDocument();
  });
});
