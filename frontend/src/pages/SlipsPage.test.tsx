import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "../context/AuthContext";
import { setAccessToken } from "../lib/tokenStore";
import { SlipsPage } from "./SlipsPage";
import type { Slip, TeamMember } from "../types/api";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/** Phase 16: AuthProvider's session-hydration effect gates on the readable
 * CSRF cookie (there is no frontend-visible refresh token anymore -- see
 * src/lib/tokenStore.ts::getCsrfToken). Setting it here is what makes the
 * provider actually call the mocked `authMeRoute()` below and populate
 * `user`. */
function setCsrfCookie(value: string | null) {
  if (value) {
    document.cookie = `csrf_token=${value}; path=/`;
  } else {
    document.cookie = "csrf_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  }
}

const OWNER: TeamMember = {
  id: "11111111-1111-1111-1111-111111111111",
  company_id: "cccccccc-cccc-cccc-cccc-cccccccccccc",
  email: "owner@example.com",
  full_name: "Owner Person",
  role: "owner",
  is_active: true,
  skills: [],
  address_text: null,
  home_latitude: null,
  home_longitude: null,
};

const WET_SLIP: Slip = {
  id: "ffffffff-0000-0000-0000-000000000001",
  company_id: OWNER.company_id,
  identifier: "A-12",
  slip_type: "wet_slip",
  status: "available",
  length_ft: "40.00",
  width_ft: "14.00",
  depth_ft: "6.00",
  rack_level: null,
  rack_position: null,
  latitude: null,
  longitude: null,
  monthly_rate: "450.00",
  daily_rate: "35.00",
  notes: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

interface Route {
  match: RegExp;
  respond: (options?: RequestInit) => Response;
}

function installFetchRouter(routes: Route[]) {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockImplementation((url: string, options?: RequestInit) => {
    const idx = routes.findIndex((r) => r.match.test(String(url)));
    if (idx === -1) {
      throw new Error(`Unexpected fetch: ${options?.method ?? "GET"} ${url}`);
    }
    const [route] = routes.splice(idx, 1);
    return Promise.resolve(route.respond(options));
  });
}

function authMeRoute(): Route {
  return { match: /\/auth\/me/, respond: () => jsonResponse(OWNER) };
}
function slipsListRoute(slips: Slip[]): Route {
  return { match: /\/slips(\?.*)?$/, respond: () => jsonResponse(slips) };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <SlipsPage />
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe("SlipsPage", () => {
  beforeEach(() => {
    localStorage.clear();
    setAccessToken("access-token");
    setCsrfCookie("test-csrf-token");
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    setCsrfCookie(null);
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("renders the slip list", async () => {
    installFetchRouter([authMeRoute(), slipsListRoute([WET_SLIP])]);

    renderPage();

    const row = (await screen.findByText("A-12")).closest("tr");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText("Wet slip")).toBeInTheDocument();
    expect(within(row as HTMLElement).getByText("available")).toBeInTheDocument();
  });

  it("creates a slip via POST /slips", async () => {
    installFetchRouter([authMeRoute(), slipsListRoute([WET_SLIP])]);

    renderPage();
    await screen.findByText("A-12");

    await userEvent.click(screen.getByRole("button", { name: /new slip/i }));
    expect(await screen.findByRole("heading", { name: /new slip/i })).toBeInTheDocument();

    const created: Slip = { ...WET_SLIP, id: "new-id", identifier: "B-7" };
    installFetchRouter([
      {
        match: /\/slips$/,
        respond: (options) => {
          expect(options?.method).toBe("POST");
          const body = JSON.parse(options?.body as string);
          expect(body.identifier).toBe("B-7");
          return jsonResponse(created, 201);
        },
      },
      slipsListRoute([WET_SLIP, created]),
    ]);

    await userEvent.type(screen.getByLabelText(/^Identifier$/i), "B-7");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: /new slip/i })).not.toBeInTheDocument(),
    );
  });

  it("shows rack fields for dry-stack slip type", async () => {
    const dryStack: Slip = {
      ...WET_SLIP,
      id: "dry-1",
      identifier: "R-3",
      slip_type: "dry_stack",
      length_ft: null,
      width_ft: null,
      depth_ft: null,
      rack_level: 2,
      rack_position: "North",
    };
    installFetchRouter([authMeRoute(), slipsListRoute([dryStack])]);

    renderPage();
    const row = (await screen.findByText("R-3")).closest("tr");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText("Dry stack")).toBeInTheDocument();
    expect(within(row as HTMLElement).getByText(/Level 2, North/)).toBeInTheDocument();
  });
});
