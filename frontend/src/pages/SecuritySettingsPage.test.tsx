import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setAccessToken } from "../lib/tokenStore";
import { SecuritySettingsPage } from "./SecuritySettingsPage";

function jsonResponse(body: unknown, status = 200) {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: status === 204 ? {} : { "content-type": "application/json" },
  });
}

interface Route {
  match: RegExp;
  respond: (options?: RequestInit) => Response;
}

/** Same "consume in order, match by URL" fetch router as TeamPage.test.tsx
 * -- see that file for the full rationale (this page has no competing
 * GET /auth/me race since it renders outside AuthProvider, but the pattern
 * still keeps each test's expectations next to the request they answer). */
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

function statusRoute(body: { mfa_enabled: boolean; remaining_backup_codes: number }): Route {
  return { match: /\/users\/me\/mfa$/, respond: () => jsonResponse(body) };
}

function renderPage() {
  return render(<SecuritySettingsPage />);
}

describe("SecuritySettingsPage", () => {
  beforeEach(() => {
    setAccessToken("access-token");
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows the 'off' state with a setup button when MFA is not enabled", async () => {
    installFetchRouter([statusRoute({ mfa_enabled: false, remaining_backup_codes: 0 })]);

    renderPage();

    expect(await screen.findByText("Two-factor authentication is off")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /set up two-factor authentication/i }),
    ).toBeInTheDocument();
  });

  it("shows the 'on' state with remaining backup code count when MFA is enabled", async () => {
    installFetchRouter([statusRoute({ mfa_enabled: true, remaining_backup_codes: 7 })]);

    renderPage();

    expect(await screen.findByText("Two-factor authentication is on")).toBeInTheDocument();
    expect(screen.getByText(/7 unused backup codes remaining/i)).toBeInTheDocument();
  });

  it("starts enrollment and renders the QR code + manual secret", async () => {
    installFetchRouter([statusRoute({ mfa_enabled: false, remaining_backup_codes: 0 })]);
    renderPage();
    await screen.findByText("Two-factor authentication is off");

    installFetchRouter([
      {
        match: /\/users\/me\/mfa\/enroll$/,
        respond: () =>
          jsonResponse({
            otpauth_uri: "otpauth://totp/HarborIQ:user?secret=ABCDEFGHIJKLMNOP&issuer=HarborIQ",
            secret: "ABCDEFGHIJKLMNOP",
          }),
      },
    ]);
    await userEvent.click(screen.getByRole("button", { name: /set up two-factor/i }));

    expect(await screen.findByText("Scan this QR code")).toBeInTheDocument();
    expect(screen.getByText("ABCDEFGHIJKLMNOP")).toBeInTheDocument();
  });

  it("confirms enrollment and shows the one-time backup codes", async () => {
    installFetchRouter([statusRoute({ mfa_enabled: false, remaining_backup_codes: 0 })]);
    renderPage();
    await screen.findByText("Two-factor authentication is off");

    installFetchRouter([
      {
        match: /\/users\/me\/mfa\/enroll$/,
        respond: () =>
          jsonResponse({
            otpauth_uri: "otpauth://totp/HarborIQ:user?secret=ABCDEFGHIJKLMNOP&issuer=HarborIQ",
            secret: "ABCDEFGHIJKLMNOP",
          }),
      },
    ]);
    await userEvent.click(screen.getByRole("button", { name: /set up two-factor/i }));
    await screen.findByText("Scan this QR code");

    const backupCodes = Array.from({ length: 10 }, (_, i) => `CODE${i}-CODE${i}`);
    installFetchRouter([
      {
        match: /\/users\/me\/mfa\/confirm$/,
        respond: () => jsonResponse({ mfa_enabled: true, backup_codes: backupCodes }),
      },
    ]);

    await userEvent.type(screen.getByLabelText(/6-digit code/i), "123456");
    await userEvent.click(screen.getByRole("button", { name: /verify and turn on/i }));

    expect(await screen.findByText("Save your backup codes")).toBeInTheDocument();
    expect(screen.getByText("CODE0-CODE0")).toBeInTheDocument();
    expect(screen.getByText("CODE9-CODE9")).toBeInTheDocument();
  });

  it("shows an error and does not activate MFA when confirm is rejected", async () => {
    installFetchRouter([statusRoute({ mfa_enabled: false, remaining_backup_codes: 0 })]);
    renderPage();
    await screen.findByText("Two-factor authentication is off");

    installFetchRouter([
      {
        match: /\/users\/me\/mfa\/enroll$/,
        respond: () =>
          jsonResponse({
            otpauth_uri: "otpauth://totp/HarborIQ:user?secret=ABCDEFGHIJKLMNOP&issuer=HarborIQ",
            secret: "ABCDEFGHIJKLMNOP",
          }),
      },
    ]);
    await userEvent.click(screen.getByRole("button", { name: /set up two-factor/i }));
    await screen.findByText("Scan this QR code");

    installFetchRouter([
      {
        match: /\/users\/me\/mfa\/confirm$/,
        respond: () => jsonResponse({ detail: "invalid code" }, 401),
      },
    ]);

    await userEvent.type(screen.getByLabelText(/6-digit code/i), "000000");
    await userEvent.click(screen.getByRole("button", { name: /verify and turn on/i }));

    expect(await screen.findByText(/didn't match|invalid code/i)).toBeInTheDocument();
  });

  it("disables MFA after confirming with a password", async () => {
    installFetchRouter([statusRoute({ mfa_enabled: true, remaining_backup_codes: 5 })]);
    renderPage();
    await screen.findByText("Two-factor authentication is on");

    await userEvent.click(screen.getByRole("button", { name: /turn off/i }));
    await userEvent.type(screen.getByLabelText(/password/i), "correct-horse-battery-staple");

    installFetchRouter([
      { match: /\/users\/me\/mfa\/disable$/, respond: () => jsonResponse(null, 204) },
      statusRoute({ mfa_enabled: false, remaining_backup_codes: 0 }),
    ]);
    await userEvent.click(screen.getByRole("button", { name: /confirm turn off/i }));

    expect(await screen.findByText("Two-factor authentication is off")).toBeInTheDocument();
  });

  it("shows an error and keeps MFA enabled when disable is given the wrong password", async () => {
    installFetchRouter([statusRoute({ mfa_enabled: true, remaining_backup_codes: 5 })]);
    renderPage();
    await screen.findByText("Two-factor authentication is on");

    await userEvent.click(screen.getByRole("button", { name: /turn off/i }));
    await userEvent.type(screen.getByLabelText(/password/i), "wrong-password");

    installFetchRouter([
      { match: /\/users\/me\/mfa\/disable$/, respond: () => jsonResponse({ detail: "invalid password" }, 401) },
    ]);
    await userEvent.click(screen.getByRole("button", { name: /confirm turn off/i }));

    expect(await screen.findByText(/invalid password|unable to disable/i)).toBeInTheDocument();
    expect(screen.getByText("Two-factor authentication is on")).toBeInTheDocument();
  });
});
