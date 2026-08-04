import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setAccessToken, setRefreshToken } from "../lib/tokenStore";
import { TeamPage } from "./TeamPage";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function renderTeamPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <TeamPage />
    </QueryClientProvider>,
  );
}

describe("TeamPage", () => {
  beforeEach(() => {
    localStorage.clear();
    setAccessToken("access-token");
    setRefreshToken("refresh-token");
    vi.stubGlobal("fetch", vi.fn());
    vi.stubGlobal("navigator", {
      ...navigator,
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("sends an invite and displays the returned accept link", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        {
          email: "newhire@example.com",
          role: "office",
          full_name: null,
          company_name: "Off the Hook Marine",
          expires_in_hours: 168,
          accept_url: "http://localhost:5173/accept-invite/abc123tok",
        },
        201,
      ),
    );

    renderTeamPage();

    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/Email/i), "newhire@example.com");
    await user.selectOptions(screen.getByLabelText(/Role/i), "office");
    await user.click(screen.getByRole("button", { name: /send invite/i }));

    expect(await screen.findByText(/Invited/)).toBeInTheDocument();
    expect(screen.getByText(/newhire@example.com/)).toBeInTheDocument();
    expect(screen.getByText("http://localhost:5173/accept-invite/abc123tok")).toBeInTheDocument();

    const [url, options] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/auth/invites");
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body)).toEqual({
      email: "newhire@example.com",
      role: "office",
      full_name: undefined,
    });
  });

  it("shows a server error (e.g. duplicate email) instead of a success banner", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "email is already registered" }, 409));

    renderTeamPage();

    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/Email/i), "taken@example.com");
    await user.click(screen.getByRole("button", { name: /send invite/i }));

    expect(await screen.findByText(/already registered/)).toBeInTheDocument();
  });
});
