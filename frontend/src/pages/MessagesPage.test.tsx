import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setAccessToken } from "../lib/tokenStore";
import { MessagesPage } from "./MessagesPage";

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
      <MessagesPage />
    </QueryClientProvider>,
  );
}

describe("MessagesPage", () => {
  beforeEach(() => {
    localStorage.clear();
    setAccessToken("access-token");
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("lists inbox messages with a customer label and unread badge", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse([
        {
          id: "m1",
          company_id: "co1",
          customer_id: "cust-1",
          job_id: null,
          sender_type: "customer",
          sender_user_id: null,
          body: "When will my boat be ready?",
          created_at: "2026-08-01T12:00:00Z",
          read_at: null,
          customer_label: "Jamie Halyard",
        },
      ]),
    );

    renderPage();

    expect(await screen.findByText("Jamie Halyard")).toBeInTheDocument();
    expect(screen.getByText("When will my boat be ready?")).toBeInTheDocument();
    expect(screen.getByText("Unread")).toBeInTheDocument();

    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/messages");
  });

  it("sends a reply to the selected customer's thread", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse([
          {
            id: "m1",
            company_id: "co1",
            customer_id: "cust-1",
            job_id: null,
            sender_type: "customer",
            sender_user_id: null,
            body: "When will my boat be ready?",
            created_at: "2026-08-01T12:00:00Z",
            read_at: null,
            customer_label: "Jamie Halyard",
          },
        ]),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          id: "m2",
          company_id: "co1",
          customer_id: "cust-1",
          job_id: null,
          sender_type: "staff",
          sender_user_id: "u1",
          body: "Friday afternoon!",
          created_at: "2026-08-01T13:00:00Z",
          read_at: null,
        }),
      )
      .mockResolvedValueOnce(jsonResponse([]));

    renderPage();
    await screen.findByText("Jamie Halyard");

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /reply/i }));
    await user.type(screen.getByLabelText("Reply"), "Friday afternoon!");
    await user.click(screen.getByRole("button", { name: /send reply/i }));

    const [url, options] = fetchMock.mock.calls[1];
    expect(String(url)).toContain("/messages");
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body)).toEqual({
      customer_id: "cust-1",
      body: "Friday afternoon!",
      job_id: undefined,
    });
  });

  it("shows an empty state when there are no messages", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse([]));

    renderPage();

    expect(await screen.findByText(/No messages yet/)).toBeInTheDocument();
  });
});
