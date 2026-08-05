import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "../context/AuthContext";
import { setAccessToken, setRefreshToken } from "../lib/tokenStore";
import { PurchaseOrdersPage } from "./PurchaseOrdersPage";
import type { InventoryItem, PurchaseOrder, ReorderSuggestion, TeamMember, Vendor } from "../types/api";

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

const VENDOR: Vendor = {
  id: "bbbbbbbb-0000-0000-0000-000000000001",
  company_id: OWNER.company_id,
  name: "Acme Marine Supply",
  contact_email: null,
  contact_phone: null,
  notes: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
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
  default_vendor_id: VENDOR.id,
  created_at: "2026-01-01T00:00:00Z",
};

const SUBMITTED_PO: PurchaseOrder = {
  id: "dddddddd-0000-0000-0000-000000000001",
  company_id: OWNER.company_id,
  vendor_id: VENDOR.id,
  status: "submitted",
  created_by: OWNER.id,
  submitted_at: "2026-01-02T00:00:00Z",
  received_at: null,
  notes: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
  line_items: [
    {
      id: "eeeeeeee-0000-0000-0000-000000000001",
      inventory_item_id: ITEM.id,
      quantity_ordered: 10,
      quantity_received: 0,
      unit_cost: "12.50",
    },
  ],
};

const SUGGESTION: ReorderSuggestion = {
  id: ITEM.id,
  name: ITEM.name,
  sku: ITEM.sku,
  quantity_on_hand: ITEM.quantity_on_hand,
  reorder_point: ITEM.reorder_point,
  default_vendor_id: VENDOR.id,
  unit_cost: ITEM.unit_cost,
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
function posListRoute(pos: PurchaseOrder[]): Route {
  return { match: /\/purchase-orders(\?.*)?$/, respond: () => jsonResponse(pos) };
}
function vendorsListRoute(vendors: Vendor[]): Route {
  return { match: /\/vendors(\?.*)?$/, respond: () => jsonResponse(vendors) };
}
function inventoryListRoute(items: InventoryItem[]): Route {
  return { match: /\/inventory(\?.*)?$/, respond: () => jsonResponse(items) };
}
function suggestionsRoute(suggestions: ReorderSuggestion[]): Route {
  return { match: /\/inventory\/reorder-suggestions$/, respond: () => jsonResponse(suggestions) };
}

function baseRoutes(pos: PurchaseOrder[] = [], suggestions: ReorderSuggestion[] = []) {
  return [
    authMeRoute(),
    posListRoute(pos),
    vendorsListRoute([VENDOR]),
    inventoryListRoute([ITEM]),
    suggestionsRoute(suggestions),
  ];
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <PurchaseOrdersPage />
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe("PurchaseOrdersPage", () => {
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

  it("renders purchase orders with vendor name and status", async () => {
    installFetchRouter(baseRoutes([SUBMITTED_PO]));

    renderPage();

    expect(await screen.findByText("Acme Marine Supply")).toBeInTheDocument();
    expect(screen.getByText("submitted")).toBeInTheDocument();
  });

  it("shows reorder suggestions and generates a draft PO", async () => {
    installFetchRouter(baseRoutes([], [SUGGESTION]));

    renderPage();

    expect(await screen.findByText(/Reorder suggestions/i)).toBeInTheDocument();
    expect(screen.getByText(/Fuel Filter \(2\/5\)/)).toBeInTheDocument();

    const draftPo: PurchaseOrder = { ...SUBMITTED_PO, id: "generated-po", status: "draft" };
    installFetchRouter([
      {
        match: /\/inventory\/reorder-suggestions\/generate-po/,
        respond: (options) => {
          expect(options?.method).toBe("POST");
          const body = JSON.parse(options?.body as string);
          expect(body.vendor_id).toBe(VENDOR.id);
          return jsonResponse(draftPo, 201);
        },
      },
      ...baseRoutes([draftPo], []),
    ]);

    await userEvent.click(screen.getByRole("button", { name: /^draft po$/i }));

    await waitFor(() => expect(screen.getByText("draft")).toBeInTheDocument());
  });

  it("submits a draft purchase order", async () => {
    const draftPo: PurchaseOrder = { ...SUBMITTED_PO, status: "draft" };
    installFetchRouter(baseRoutes([draftPo]));

    renderPage();
    await screen.findByText("draft");

    const submittedPo: PurchaseOrder = { ...draftPo, status: "submitted" };
    installFetchRouter([
      {
        match: /\/purchase-orders\/[0-9a-f-]+\/submit/,
        respond: (options) => {
          expect(options?.method).toBe("POST");
          return jsonResponse(submittedPo);
        },
      },
      ...baseRoutes([submittedPo]),
    ]);

    await userEvent.click(screen.getByRole("button", { name: /^submit$/i }));

    await waitFor(() => expect(screen.getByText("submitted")).toBeInTheDocument());
  });

  it("receives a shipment against a submitted PO and closes the modal", async () => {
    installFetchRouter(baseRoutes([SUBMITTED_PO]));

    renderPage();
    await screen.findByText("submitted");

    await userEvent.click(screen.getByRole("button", { name: /receive/i }));
    expect(await screen.findByText(/Receive shipment/i)).toBeInTheDocument();

    const receivedPo: PurchaseOrder = {
      ...SUBMITTED_PO,
      status: "received",
      line_items: [{ ...SUBMITTED_PO.line_items[0], quantity_received: 10 }],
    };
    installFetchRouter([
      {
        match: /\/purchase-orders\/[0-9a-f-]+\/receive/,
        respond: (options) => {
          expect(options?.method).toBe("POST");
          const body = JSON.parse(options?.body as string);
          expect(body.receipts[0].quantity).toBe(10);
          return jsonResponse(receivedPo);
        },
      },
      ...baseRoutes([receivedPo]),
    ]);

    await userEvent.click(screen.getByRole("button", { name: /record receipt/i }));

    await waitFor(() => expect(screen.queryByText(/Receive shipment/i)).not.toBeInTheDocument());
  });
});
