import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "../context/AuthContext";
import { setAccessToken, setRefreshToken } from "../lib/tokenStore";
import { InventoryPage } from "./InventoryPage";
import type { InventoryItem, TeamMember, Vendor } from "../types/api";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
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

const ITEM: InventoryItem = {
  id: "aaaaaaaa-0000-0000-0000-000000000001",
  company_id: OWNER.company_id,
  name: "Fuel Filter",
  sku: "FF-100",
  unit_cost: "12.50",
  retail_price: "24.99",
  currency: "USD",
  quantity_on_hand: 2,
  reorder_point: 5,
  low_stock_alerted: false,
  default_vendor_id: null,
  created_at: "2026-01-01T00:00:00Z",
};

const VENDOR: Vendor = {
  id: "bbbbbbbb-0000-0000-0000-000000000001",
  company_id: OWNER.company_id,
  name: "Acme Marine Supply",
  contact_email: "orders@acme.example",
  contact_phone: null,
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
function inventoryListRoute(items: InventoryItem[]): Route {
  return { match: /\/inventory(\?.*)?$/, respond: () => jsonResponse(items) };
}
function vendorsListRoute(vendors: Vendor[]): Route {
  return { match: /\/vendors(\?.*)?$/, respond: () => jsonResponse(vendors) };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <InventoryPage />
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe("InventoryPage", () => {
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

  it("renders inventory items and flags low stock", async () => {
    installFetchRouter([authMeRoute(), inventoryListRoute([ITEM]), vendorsListRoute([VENDOR])]);

    renderPage();

    expect(await screen.findByText("Fuel Filter")).toBeInTheDocument();
    expect(screen.getByText("low")).toBeInTheDocument();
  });

  it("looks up an item by SKU via GET /inventory/lookup", async () => {
    installFetchRouter([authMeRoute(), inventoryListRoute([ITEM]), vendorsListRoute([VENDOR])]);

    renderPage();
    await screen.findByText("Fuel Filter");

    installFetchRouter([
      {
        match: /\/inventory\/lookup/,
        respond: () => jsonResponse(ITEM),
      },
    ]);

    await userEvent.type(screen.getByLabelText(/Look up by SKU/i), "FF-100");
    await userEvent.click(screen.getByRole("button", { name: /look up/i }));

    expect(await screen.findByText(/on hand: 2/)).toBeInTheDocument();
  });

  it("creates a new inventory item via POST /inventory", async () => {
    installFetchRouter([authMeRoute(), inventoryListRoute([ITEM]), vendorsListRoute([VENDOR])]);

    renderPage();
    await screen.findByText("Fuel Filter");

    await userEvent.click(screen.getByRole("button", { name: /new item/i }));
    expect(await screen.findByText(/New inventory item/i)).toBeInTheDocument();

    const created: InventoryItem = { ...ITEM, id: "new-id", name: "Oil Filter", sku: "OF-1" };
    installFetchRouter([
      {
        match: /\/inventory$/,
        respond: (options) => {
          expect(options?.method).toBe("POST");
          const body = JSON.parse(options?.body as string);
          expect(body.name).toBe("Oil Filter");
          return jsonResponse(created, 201);
        },
      },
      inventoryListRoute([ITEM, created]),
    ]);

    await userEvent.type(screen.getByLabelText(/^Name$/i), "Oil Filter");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(screen.queryByText(/New inventory item/i)).not.toBeInTheDocument());
  });
});
