import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "../context/AuthContext";
import { setAccessToken } from "../lib/tokenStore";
import { VendorsPage } from "./VendorsPage";
import type { TeamMember, Vendor } from "../types/api";

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
 * `user`, which this page's role-gated "New Vendor" button depends on. */
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

const VENDOR: Vendor = {
  id: "bbbbbbbb-0000-0000-0000-000000000001",
  company_id: OWNER.company_id,
  name: "Acme Marine Supply",
  contact_email: "orders@acme.example",
  contact_phone: "941-555-0100",
  notes: "Net 30",
  is_active: true,
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
function vendorsListRoute(vendors: Vendor[]): Route {
  return { match: /\/vendors(\?.*)?$/, respond: () => jsonResponse(vendors) };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <VendorsPage />
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe("VendorsPage", () => {
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

  it("renders the vendor list", async () => {
    installFetchRouter([authMeRoute(), vendorsListRoute([VENDOR])]);

    renderPage();

    expect(await screen.findByText("Acme Marine Supply")).toBeInTheDocument();
    expect(screen.getByText("orders@acme.example")).toBeInTheDocument();
  });

  it("creates a vendor via POST /vendors", async () => {
    installFetchRouter([authMeRoute(), vendorsListRoute([VENDOR])]);

    renderPage();
    await screen.findByText("Acme Marine Supply");

    await userEvent.click(screen.getByRole("button", { name: /new vendor/i }));
    expect(await screen.findByRole("heading", { name: /new vendor/i })).toBeInTheDocument();

    const created: Vendor = { ...VENDOR, id: "new-id", name: "Marine Parts Co" };
    installFetchRouter([
      {
        match: /\/vendors$/,
        respond: (options) => {
          expect(options?.method).toBe("POST");
          const body = JSON.parse(options?.body as string);
          expect(body.name).toBe("Marine Parts Co");
          return jsonResponse(created, 201);
        },
      },
      vendorsListRoute([VENDOR, created]),
    ]);

    await userEvent.type(screen.getByLabelText(/^Name$/i), "Marine Parts Co");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: /new vendor/i })).not.toBeInTheDocument(),
    );
  });

  it("archives a vendor via POST /vendors/{id}/status (Phase 17 Area F)", async () => {
    installFetchRouter([authMeRoute(), vendorsListRoute([VENDOR])]);

    renderPage();
    await screen.findByText("Acme Marine Supply");

    const archived: Vendor = { ...VENDOR, is_active: false };
    installFetchRouter([
      {
        match: /\/vendors\/bbbbbbbb-0000-0000-0000-000000000001\/status$/,
        respond: (options) => {
          expect(options?.method).toBe("POST");
          const body = JSON.parse(options?.body as string);
          expect(body.is_active).toBe(false);
          return jsonResponse(archived);
        },
      },
      vendorsListRoute([archived]),
    ]);

    await userEvent.click(screen.getByRole("button", { name: /^archive$/i }));

    expect(await screen.findByText("Archived")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^reactivate$/i })).toBeInTheDocument();
  });

  it("shows the archived-vendors toggle and requests include_inactive", async () => {
    installFetchRouter([authMeRoute(), vendorsListRoute([VENDOR])]);

    renderPage();
    await screen.findByText("Acme Marine Supply");

    const archived: Vendor = { ...VENDOR, id: "archived-id", name: "Old Supplier", is_active: false };
    installFetchRouter([
      {
        match: /\/vendors\?.*include_inactive=true/,
        respond: () => jsonResponse([VENDOR, archived]),
      },
    ]);

    await userEvent.click(screen.getByLabelText(/show archived vendors/i));

    expect(await screen.findByText("Old Supplier")).toBeInTheDocument();
  });
});
