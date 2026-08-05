import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "../context/AuthContext";
import { setAccessToken } from "../lib/tokenStore";
import { SlipReservationsPage } from "./SlipReservationsPage";
import type { Customer, Slip, SlipReservation, TeamMember } from "../types/api";

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

const SLIP: Slip = {
  id: "ffffffff-0000-0000-0000-000000000001",
  company_id: OWNER.company_id,
  identifier: "A-12",
  slip_type: "wet_slip",
  status: "occupied",
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

const CUSTOMER: Customer = {
  id: "22222222-0000-0000-0000-000000000001",
  company_id: OWNER.company_id,
  first_name: "Jane",
  last_name: "Boater",
  company_name: null,
  email: "jane@example.com",
  phone: null,
  address_line1: null,
  address_line2: null,
  city: null,
  state: null,
  postal_code: null,
  country: null,
  notes: null,
  latitude: null,
  longitude: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const RESERVATION: SlipReservation = {
  id: "33333333-0000-0000-0000-000000000001",
  company_id: OWNER.company_id,
  slip_id: SLIP.id,
  customer_id: CUSTOMER.id,
  vessel_id: null,
  status: "pending",
  start_date: "2026-06-01",
  end_date: "2026-06-05",
  checked_in_at: null,
  checked_out_at: null,
  cancelled_at: null,
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
function reservationsListRoute(reservations: SlipReservation[]): Route {
  return { match: /\/slip-reservations(\?.*)?$/, respond: () => jsonResponse(reservations) };
}
function slipsListRoute(slips: Slip[]): Route {
  return { match: /\/slips(\?.*)?$/, respond: () => jsonResponse(slips) };
}
function customersListRoute(customers: Customer[]): Route {
  return { match: /\/customers(\?.*)?$/, respond: () => jsonResponse(customers) };
}

function baseRoutes(reservations: SlipReservation[] = []) {
  return [
    authMeRoute(),
    reservationsListRoute(reservations),
    slipsListRoute([SLIP]),
    customersListRoute([CUSTOMER]),
  ];
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <SlipReservationsPage />
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe("SlipReservationsPage", () => {
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

  it("renders reservations with slip identifier, customer name, and status", async () => {
    installFetchRouter(baseRoutes([RESERVATION]));

    renderPage();

    expect(await screen.findByText("A-12")).toBeInTheDocument();
    expect(screen.getByText("Jane Boater")).toBeInTheDocument();
    expect(screen.getByText("pending")).toBeInTheDocument();
  });

  it("confirms a pending reservation", async () => {
    installFetchRouter(baseRoutes([RESERVATION]));

    renderPage();
    await screen.findByText("A-12");

    const confirmed: SlipReservation = { ...RESERVATION, status: "confirmed" };
    installFetchRouter([
      {
        match: /\/slip-reservations\/.+\/confirm$/,
        respond: (options) => {
          expect(options?.method).toBe("POST");
          return jsonResponse(confirmed);
        },
      },
      ...baseRoutes([confirmed]),
    ]);

    await userEvent.click(screen.getByRole("button", { name: /^confirm$/i }));

    await waitFor(() => expect(screen.getByText("confirmed")).toBeInTheDocument());
  });

  it("creates a reservation via POST /slip-reservations", async () => {
    installFetchRouter(baseRoutes([]));

    renderPage();
    await screen.findByRole("button", { name: /new reservation/i });

    await userEvent.click(screen.getByRole("button", { name: /new reservation/i }));
    expect(await screen.findByRole("heading", { name: /new reservation/i })).toBeInTheDocument();

    installFetchRouter([
      {
        match: /\/slip-reservations$/,
        respond: (options) => {
          expect(options?.method).toBe("POST");
          const body = JSON.parse(options?.body as string);
          expect(body.slip_id).toBe(SLIP.id);
          expect(body.customer_id).toBe(CUSTOMER.id);
          return jsonResponse(RESERVATION, 201);
        },
      },
      ...baseRoutes([RESERVATION]),
    ]);

    await userEvent.selectOptions(screen.getByLabelText(/^Slip$/i), SLIP.id);
    await userEvent.selectOptions(screen.getByLabelText(/^Customer$/i), CUSTOMER.id);
    await userEvent.type(screen.getByLabelText(/^Start date$/i), "2026-06-01");
    await userEvent.type(screen.getByLabelText(/^End date$/i), "2026-06-05");
    await userEvent.click(screen.getByRole("button", { name: /^create$/i }));

    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: /new reservation/i })).not.toBeInTheDocument(),
    );
  });
});
