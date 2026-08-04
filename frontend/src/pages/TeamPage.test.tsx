import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "../context/AuthContext";
import { setAccessToken, setRefreshToken } from "../lib/tokenStore";
import { TeamPage } from "./TeamPage";
import type { TeamMember } from "../types/api";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const SELF: TeamMember = {
  id: "11111111-1111-1111-1111-111111111111",
  company_id: "cccccccc-cccc-cccc-cccc-cccccccccccc",
  email: "owner@example.com",
  full_name: "Owner Person",
  role: "owner",
  is_active: true,
  skills: ["electrical"],
  address_text: "1100 23rd St, Sarasota, FL 34234",
  home_latitude: "27.340000",
  home_longitude: "-82.540000",
};

const TECH: TeamMember = {
  id: "22222222-2222-2222-2222-222222222222",
  company_id: "cccccccc-cccc-cccc-cccc-cccccccccccc",
  email: "tech@example.com",
  full_name: "Tech Person",
  role: "technician",
  is_active: true,
  skills: ["outboard"],
  address_text: "500 Dock Rd, Bradenton, FL 34208",
  home_latitude: null,
  home_longitude: null,
};

interface Route {
  match: RegExp;
  respond: (options?: RequestInit) => Response;
}

/** TeamPage mounts inside a real AuthProvider, which on mount fires
 * GET /auth/me to hydrate `user` (see AuthContext.tsx) at essentially the
 * same time TeamPage's own GET /users query fires. The two requests race,
 * so route mocked responses by URL/method rather than call order. Routes
 * are consumed in the order given for a given URL, so a test can queue a
 * pre-PATCH and post-PATCH GET /users response for the same path. */
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

function authMeRoute(user: TeamMember): Route {
  return { match: /\/auth\/me/, respond: () => jsonResponse(user) };
}

function usersListRoute(users: TeamMember[]): Route {
  return { match: /\/users$/, respond: () => jsonResponse(users) };
}

function renderTeamPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <TeamPage />
      </AuthProvider>
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

  it("renders the roster with role, skills, and geocoding status", async () => {
    installFetchRouter([authMeRoute(SELF), usersListRoute([SELF, TECH])]);

    renderTeamPage();

    expect(await screen.findByText("Owner Person")).toBeInTheDocument();
    expect(screen.getByText("Tech Person")).toBeInTheDocument();
    expect(screen.getByText("located")).toBeInTheDocument();
    expect(screen.getByText("not located")).toBeInTheDocument();
  });

  it("lets a user edit their own profile via PATCH /users/{id}", async () => {
    installFetchRouter([authMeRoute(SELF), usersListRoute([SELF, TECH])]);

    renderTeamPage();

    await screen.findByText("Owner Person");
    const ownRow = screen.getByText("Owner Person").closest("tr")!;
    await userEvent.click(within(ownRow).getByRole("button", { name: /edit/i }));

    expect(await screen.findByText(/Edit your profile/i)).toBeInTheDocument();

    const updatedSelf = { ...SELF, skills: ["electrical", "hydraulics"] };
    installFetchRouter([
      {
        match: /\/users\/[0-9a-f-]+$/,
        respond: (options) => {
          expect(options?.method).toBe("PATCH");
          const body = JSON.parse(options?.body as string);
          expect(body.skills).toEqual(["electrical", "hydraulics"]);
          // Self-edit must never send role/is_active.
          expect(body).not.toHaveProperty("role");
          expect(body).not.toHaveProperty("is_active");
          return jsonResponse(updatedSelf);
        },
      },
      usersListRoute([updatedSelf, TECH]),
    ]);

    const skillsInput = screen.getByLabelText(/Skills/i);
    await userEvent.clear(skillsInput);
    await userEvent.type(skillsInput, "electrical, hydraulics");
    await userEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(screen.queryByText(/Edit your profile/i)).not.toBeInTheDocument());
  });

  it("lets an admin change a teammate's role and active status", async () => {
    installFetchRouter([authMeRoute(SELF), usersListRoute([SELF, TECH])]);

    renderTeamPage();

    await screen.findByText("Tech Person");
    const techRow = screen.getByText("Tech Person").closest("tr")!;
    await userEvent.click(within(techRow).getByRole("button", { name: /edit/i }));

    expect(await screen.findByText(/Edit Tech Person/i)).toBeInTheDocument();
    // Admin editing someone else sees the role selector.
    const roleSelect = screen.getByLabelText(/Role/i);

    const updatedTech = { ...TECH, role: "office" as const };
    installFetchRouter([
      {
        match: /\/users\/[0-9a-f-]+$/,
        respond: (options) => {
          const body = JSON.parse(options?.body as string);
          expect(body.role).toBe("office");
          return jsonResponse(updatedTech);
        },
      },
      usersListRoute([SELF, updatedTech]),
    ]);

    await userEvent.selectOptions(roleSelect, "office");
    await userEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(screen.queryByText(/Edit Tech Person/i)).not.toBeInTheDocument());
  });

  it("sends an invite and displays the returned accept link", async () => {
    installFetchRouter([authMeRoute(SELF), usersListRoute([SELF, TECH])]);

    renderTeamPage();
    await screen.findByText("Owner Person");

    await userEvent.click(screen.getByRole("button", { name: /invite teammate/i }));

    installFetchRouter([
      {
        match: /\/auth\/invites/,
        respond: () =>
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
      },
    ]);

    await userEvent.type(screen.getByLabelText(/Email/i), "newhire@example.com");
    await userEvent.selectOptions(screen.getByLabelText(/^Role$/i), "office");
    await userEvent.click(screen.getByRole("button", { name: /send invite/i }));

    expect(await screen.findByText(/Invited/)).toBeInTheDocument();
    expect(screen.getByText(/newhire@example.com/)).toBeInTheDocument();
    expect(screen.getByText("http://localhost:5173/accept-invite/abc123tok")).toBeInTheDocument();
  });

  it("shows a server error (e.g. duplicate email) instead of a success banner", async () => {
    installFetchRouter([authMeRoute(SELF), usersListRoute([SELF, TECH])]);

    renderTeamPage();
    await screen.findByText("Owner Person");

    await userEvent.click(screen.getByRole("button", { name: /invite teammate/i }));

    installFetchRouter([
      {
        match: /\/auth\/invites/,
        respond: () => jsonResponse({ detail: "email is already registered" }, 409),
      },
    ]);

    await userEvent.type(screen.getByLabelText(/Email/i), "taken@example.com");
    await userEvent.click(screen.getByRole("button", { name: /send invite/i }));

    expect(await screen.findByText(/already registered/)).toBeInTheDocument();
  });
});
