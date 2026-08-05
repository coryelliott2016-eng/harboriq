import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "../context/AuthContext";
import { setAccessToken } from "../lib/tokenStore";
import { DispatchBoardPage } from "./DispatchBoardPage";
import type { Customer, Job, TeamMember, TechnicianLocation } from "../types/api";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const OWNER: TeamMember = {
  id: "owner-1",
  company_id: "co-1",
  email: "owner@example.com",
  full_name: "Owner Person",
  role: "owner",
  is_active: true,
  skills: [],
  address_text: null,
  home_latitude: null,
  home_longitude: null,
};

const TECH: TeamMember = {
  id: "tech-1",
  company_id: "co-1",
  email: "tech@example.com",
  full_name: "Tech Person",
  role: "technician",
  is_active: true,
  skills: ["outboard"],
  address_text: "500 Dock Rd, Bradenton, FL 34208",
  home_latitude: "27.500000",
  home_longitude: "-82.570000",
};

const CUSTOMER: Customer = {
  id: "cust-1",
  company_id: "co-1",
  first_name: "Jamie",
  last_name: "Halyard",
  company_name: null,
  email: null,
  phone: "+15551234567",
  address_line1: null,
  address_line2: null,
  city: null,
  state: null,
  postal_code: null,
  country: null,
  notes: null,
  latitude: "27.340000",
  longitude: "-82.540000",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const JOB: Job = {
  id: "job-1",
  company_id: "co-1",
  customer_id: "cust-1",
  vessel_id: null,
  title: "Replace impeller",
  description: null,
  status: "scheduled",
  priority: "normal",
  scheduled_at: "2026-08-05T13:00:00Z",
  scheduled_end_at: null,
  technician_id: null,
  started_at: null,
  completed_at: null,
  canceled_at: null,
  hold_reason: null,
  notes: null,
  required_skills: [],
  dispatch_score: null,
  dispatch_score_breakdown: null,
  dispatch_scored_at: null,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

const TECH_LOCATION: TechnicianLocation = {
  id: "tech-1",
  full_name: "Tech Person",
  latitude: "27.500000",
  longitude: "-82.570000",
  is_live: false,
  location_updated_at: null,
};

interface Route {
  match: RegExp;
  respond: (options?: RequestInit) => Response;
}

function installFetchRouter(routes: Route[]) {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockImplementation((url: string, options?: RequestInit) => {
    const method = options?.method ?? "GET";
    const idx = routes.findIndex((r) => r.match.test(String(url)));
    if (idx === -1) {
      throw new Error(`Unexpected fetch: ${method} ${url}`);
    }
    const [route] = routes.splice(idx, 1);
    return Promise.resolve(route.respond(options));
  });
}

function baseRoutes(overrides: Partial<Record<string, unknown>> = {}) {
  return [
    { match: /\/auth\/me/, respond: () => jsonResponse(overrides.self ?? OWNER) },
    { match: /\/jobs\?/, respond: () => jsonResponse(overrides.jobs ?? [JOB]) },
    { match: /\/jobs$/, respond: () => jsonResponse(overrides.jobs ?? [JOB]) },
    { match: /\/users$/, respond: () => jsonResponse(overrides.users ?? [OWNER, TECH]) },
    { match: /\/customers\?/, respond: () => jsonResponse(overrides.customers ?? [CUSTOMER]) },
    { match: /\/customers$/, respond: () => jsonResponse(overrides.customers ?? [CUSTOMER]) },
    {
      match: /\/users\/technician-locations/,
      respond: () => jsonResponse(overrides.locations ?? [TECH_LOCATION]),
    },
  ];
}

function renderBoard() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AuthProvider>
          <DispatchBoardPage />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DispatchBoardPage", () => {
  beforeEach(() => {
    localStorage.clear();
    setAccessToken("access-token");
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("renders an Unassigned column plus one column per active technician", async () => {
    installFetchRouter(baseRoutes());

    renderBoard();

    expect(await screen.findByText("Replace impeller")).toBeInTheDocument();
    expect(screen.getByTestId("board-column-Unassigned")).toBeInTheDocument();
    expect(screen.getByTestId("board-column-Tech Person")).toBeInTheDocument();
  });

  it("renders the Leaflet map with a technician marker", async () => {
    installFetchRouter(baseRoutes());

    renderBoard();

    expect(await screen.findByTestId("dispatch-map")).toBeInTheDocument();
  });

  it("dragging a job onto a technician's column calls the assign endpoint", async () => {
    installFetchRouter(baseRoutes());

    renderBoard();
    const jobCard = await screen.findByTestId("board-job-job-1");
    const techColumn = screen.getByTestId("board-column-Tech Person");

    installFetchRouter([
      {
        match: /\/jobs\/job-1\/assign/,
        respond: (options) => {
          expect(options?.method).toBe("POST");
          expect(JSON.parse(options?.body as string)).toEqual({ technician_id: "tech-1" });
          return jsonResponse({ ...JOB, technician_id: "tech-1" });
        },
      },
      ...baseRoutes({ jobs: [{ ...JOB, technician_id: "tech-1" }] }),
    ]);

    const dataTransfer = {
      data: {} as Record<string, string>,
      setData(fmt: string, val: string) {
        this.data[fmt] = val;
      },
      getData(fmt: string) {
        return this.data[fmt];
      },
      effectAllowed: "",
    };

    act(() => {
      jobCard.dispatchEvent(
        Object.assign(new Event("dragstart", { bubbles: true }), { dataTransfer }),
      );
      techColumn.dispatchEvent(
        Object.assign(new Event("dragover", { bubbles: true, cancelable: true }), { dataTransfer }),
      );
      techColumn.dispatchEvent(
        Object.assign(new Event("drop", { bubbles: true, cancelable: true }), { dataTransfer }),
      );
    });

    await waitFor(() => {
      const assignCall = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.find(([url]) =>
        String(url).includes("/jobs/job-1/assign"),
      );
      expect(assignCall).toBeDefined();
    });
  });
});
