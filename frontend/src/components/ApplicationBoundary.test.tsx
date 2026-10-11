import { useContext } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter } from "react-router-dom";
import { AuthContext } from "../context/auth";
import { getAccessToken, getCsrfToken, setAccessToken } from "../lib/tokenStore";
import { ApplicationBoundary } from "./ApplicationBoundary";

const staff = {
  id: "staff-1",
  company_id: "company-1",
  email: "staff@example.com",
  full_name: "Staff Member",
  role: "owner",
  is_active: true,
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function BoundaryProbe() {
  const auth = useContext(AuthContext);
  return <p>{auth ? auth.loading ? "Staff hydration pending" : `Staff session: ${auth.user?.email ?? "none"}` : "Public route without auth provider"}</p>;
}

function renderBoundary(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <nav>
        <Link to="/intelligence-lab">Visit public lab</Link>
        <Link to="/jobs">Visit staff app</Link>
      </nav>
      <ApplicationBoundary><BoundaryProbe /></ApplicationBoundary>
    </MemoryRouter>,
  );
}

describe("ApplicationBoundary", () => {
  beforeEach(() => {
    const cookieName = import.meta.env.VITE_CSRF_COOKIE_NAME ?? "csrf_token";
    document.cookie = `${cookieName}=existing-csrf; path=/`;
    setAccessToken("existing-staff-token");
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    const cookieName = import.meta.env.VITE_CSRF_COOKIE_NAME ?? "csrf_token";
    document.cookie = `${cookieName}=; Max-Age=0; path=/`;
    setAccessToken(null);
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it.each(["/intelligence-lab", "/intelligence-lab/", "/INTELLIGENCE-LAB", "/Intelligence-Lab/?source=public"])(
    "skips hydration on a hard load at %s even with a staff CSRF cookie",
    (path) => {
      renderBoundary(path);
      expect(screen.getByText("Public route without auth provider")).toBeInTheDocument();
      expect(fetch).not.toHaveBeenCalled();
      expect(getAccessToken()).toBe("existing-staff-token");
      expect(getCsrfToken()).toBe("existing-csrf");
    },
  );

  it.each(["/jobs", "/login", "/intelligence-lab/settings"])(
    "preserves staff provider hydration for other routes including %s",
    async (path) => {
      vi.mocked(fetch).mockResolvedValueOnce(json(staff));
      renderBoundary(path);
      expect(await screen.findByText("Staff session: staff@example.com")).toBeInTheDocument();
      expect(fetch).toHaveBeenCalledTimes(1);
      const [url, options] = vi.mocked(fetch).mock.calls[0];
      expect(url).toMatch(/\/auth\/me$/);
      expect(options!.credentials).toBe("include");
      expect(new Headers(options!.headers).get("Authorization")?.split(" ")).toEqual(["Bearer", "existing-staff-token"]);
    },
  );

  it("reestablishes staff hydration after client navigation out of the public lab", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(json(staff)).mockResolvedValueOnce(json(staff));
    renderBoundary("/intelligence-lab");
    const user = userEvent.setup();
    expect(fetch).not.toHaveBeenCalled();
    await user.click(screen.getByRole("link", { name: "Visit staff app" }));
    expect(await screen.findByText("Staff session: staff@example.com")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("link", { name: "Visit public lab" }));
    expect(screen.getByText("Public route without auth provider")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(getAccessToken()).toBe("existing-staff-token");
    expect(getCsrfToken()).toBe("existing-csrf");

    await user.click(screen.getByRole("link", { name: "Visit staff app" }));
    expect(await screen.findByText("Staff session: staff@example.com")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("leaves the normal staff refresh flow intact after navigating from the lab", async () => {
    setAccessToken(null);
    vi.mocked(fetch)
      .mockResolvedValueOnce(json({}, 401))
      .mockResolvedValueOnce(json({ tokens: { access_token: "renewed-staff-token", token_type: "bearer" }, user: staff }))
      .mockResolvedValueOnce(json(staff));
    renderBoundary("/intelligence-lab");
    expect(fetch).not.toHaveBeenCalled();
    await userEvent.setup().click(screen.getByRole("link", { name: "Visit staff app" }));
    expect(await screen.findByText("Staff session: staff@example.com")).toBeInTheDocument();
    const calls = vi.mocked(fetch).mock.calls;
    expect(calls.map(([url]) => String(url).split("/").pop())).toEqual(["me", "refresh", "me"]);
    expect(calls[1][1]).toMatchObject({
      credentials: "include",
      headers: { "X-CSRF-Token": "existing-csrf" },
    });
    expect(getAccessToken()).toBe("renewed-staff-token");
  });
});
