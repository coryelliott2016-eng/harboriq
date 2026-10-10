import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import App from "../App";
import { IntelligenceLabPage } from "./IntelligenceLabPage";

const session = {
  session_token: "public-demo-token",
  expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
  requests_remaining: 3,
};
const result = {
  mode: "live_public_data",
  sector: "service",
  summary: "Latest NOAA water level: 0.42 m.",
  source_url: "https://tidesandcurrents.noaa.gov/stationhome.html?id=8726520",
  source_name: "NOAA CO-OPS",
  retrieved_at: "2026-10-10T03:00:00Z",
  observed_at: "2026-10-10T02:54:00Z",
  station: "8726520",
  product: "water_level",
  measurements: [{ time: "2026-10-10 02:54", value: "0.42", unit: "m" }],
  warnings: ["Preliminary observation; data may be delayed."],
  requests_remaining: 2,
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function mockDemo(response = result) {
  vi.mocked(fetch).mockResolvedValueOnce(json(session)).mockResolvedValueOnce(json(response));
}

async function runDemo() {
  const user = userEvent.setup();
  await user.click(screen.getByRole("checkbox", { name: /I accept the safety notice/ }));
  await user.click(screen.getByRole("button", { name: /Start demo and retrieve/ }));
  return user;
}

describe("public Intelligence Lab", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("is reachable without authentication or the tenant app shell", async () => {
    render(<MemoryRouter initialEntries={["/intelligence-lab"]}><App /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "Service / Marina Intelligence Lab" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("requires safety consent, uses only allowlisted water-level stations, and does not require a lead", async () => {
    render(<IntelligenceLabPage />);
    expect(screen.getByRole("button", { name: /Start demo and retrieve/ })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: /I accept the safety notice/ })).toBeRequired();
    fireEvent.submit(screen.getByRole("button", { name: /Start demo and retrieve/ }).closest("form")!);
    expect(fetch).not.toHaveBeenCalled();
    const stations = screen.getByLabelText("NOAA water-level station") as HTMLSelectElement;
    expect(Array.from(stations.options).map((option) => option.value)).toEqual(["8726520", "8518750", "9414290"]);
    mockDemo({ ...result, sector: "marina", station: "8518750" });
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Sector"), "marina");
    await user.selectOptions(stations, "8518750");
    await runDemo();
    await screen.findByText(result.summary);
    expect(JSON.parse(vi.mocked(fetch).mock.calls[1][1]!.body as string)).toEqual({
      sector: "marina", station: "8518750", product: "water_level",
    });
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("omits all staff credentials and stores neither demo tokens nor contact details", async () => {
    const storage = vi.spyOn(Storage.prototype, "setItem");
    mockDemo();
    render(<IntelligenceLabPage />);
    await runDemo();
    await screen.findByText(result.summary);
    const calls = vi.mocked(fetch).mock.calls;
    expect(calls[0][0]).toMatch(/\/api\/v1\/public\/intelligence\/sessions$/);
    expect(calls[0][1]).toMatchObject({
      credentials: "omit", cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ accepted_safety_notice: true }),
    });
    expect(calls[1][0]).toMatch(/\/api\/v1\/public\/intelligence\/assist$/);
    expect(calls[1][1]!.headers).toEqual({ "Content-Type": "application/json", "X-Demo-Session": session.session_token });
    for (const [, options] of calls) {
      expect(options!.credentials).toBe("omit");
      expect(new Headers(options!.headers).has("Authorization")).toBe(false);
      expect(new Headers(options!.headers).has("X-Tenant-ID")).toBe(false);
    }
    expect(storage).not.toHaveBeenCalled();
    expect(document.body).not.toHaveTextContent(session.session_token);
  });

  it("renders live status, quota, measurements, citations, source timestamps, and warnings", async () => {
    mockDemo();
    render(<IntelligenceLabPage />);
    await runDemo();
    await screen.findByText(result.summary);
    expect(screen.getByRole("status")).toHaveTextContent("Demo session active");
    expect(screen.getByRole("status")).toHaveTextContent("Requests remaining: 2");
    expect(screen.getByRole("heading", { name: /Live public data · deterministic NOAA result/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: result.source_name })).toHaveAttribute("href", result.source_url);
    expect(screen.getByText(result.retrieved_at)).toHaveAttribute("datetime", result.retrieved_at);
    expect(screen.getByText(result.observed_at)).toHaveAttribute("datetime", result.observed_at);
    expect(screen.getByText(result.warnings[0])).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "0.42" })).toBeInTheDocument();
    expect(screen.getByText(/not generative AI, equipment diagnostics/)).toBeInTheDocument();
    expect(screen.getByText(/Not for navigation, emergencies/)).toBeInTheDocument();
  });

  it("reuses the in-memory session for subsequent requests and disables an exhausted quota", async () => {
    mockDemo();
    vi.mocked(fetch).mockResolvedValueOnce(json({ ...result, requests_remaining: 0 }));
    render(<IntelligenceLabPage />);
    const user = await runDemo();
    await screen.findByText(result.summary);
    await user.click(screen.getByRole("button", { name: "Retrieve NOAA water level" }));
    await screen.findByText(/Demo quota exhausted/);
    expect(screen.getByRole("button", { name: "Retrieve NOAA water level" })).toBeDisabled();
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(vi.mocked(fetch).mock.calls[2][0]).toMatch(/\/assist$/);
  });

  it("shows expired-session errors and offers a consent-gated restart without auth refresh", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(json(session)).mockResolvedValueOnce(json({}, 410));
    render(<IntelligenceLabPage />);
    const user = await runDemo();
    expect(await screen.findByRole("alert")).toHaveTextContent("Demo session expired");
    expect(screen.getByRole("status")).toHaveTextContent("Restart to continue");
    await user.click(screen.getByRole("button", { name: "Restart demo session" }));
    expect(screen.getByRole("checkbox", { name: /I accept the safety notice/ })).not.toBeChecked();
    expect(screen.getByRole("status")).toHaveTextContent("Demo session not started");
    mockDemo();
    await runDemo();
    await screen.findByText(result.summary);
    expect(fetch).toHaveBeenCalledTimes(4);
    expect(vi.mocked(fetch).mock.calls[2][0]).toMatch(/\/sessions$/);
  });

  it("does not query an already expired session", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(json({ ...session, expires_at: "2000-01-01T00:00:00Z" }));
    render(<IntelligenceLabPage />);
    await runDemo();
    expect(await screen.findByText("Demo session expired. Restart to continue.")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it.each([429, 502, 503, 504])("shows a bounded failure for HTTP %s without fabricated results", async (status) => {
    vi.mocked(fetch).mockResolvedValueOnce(json(session)).mockResolvedValueOnce(json({}, status));
    render(<IntelligenceLabPage />);
    await runDemo();
    expect(await screen.findByRole("alert")).toHaveTextContent(status === 429 ? "Request limit reached" : /unavailable|timed out/);
    expect(screen.queryByRole("heading", { name: /Live public data · deterministic NOAA result/ })).not.toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("keeps optional contact and marketing permissions separate and sends marketing false by default", async () => {
    const storage = vi.spyOn(Storage.prototype, "setItem");
    vi.mocked(fetch).mockResolvedValueOnce(json({ id: "lead-1" }, 201));
    render(<IntelligenceLabPage />);
    const user = userEvent.setup();
    const button = screen.getByRole("button", { name: "Send contact request" });
    expect(button).toBeDisabled();
    const consent = screen.getByRole("checkbox", { name: /I consent to storing/ });
    const marketing = screen.getByRole("checkbox", { name: /Optional: I separately/ });
    expect(consent).toBeRequired();
    expect(marketing).not.toBeRequired();
    expect(marketing).not.toBeChecked();
    await user.type(screen.getByLabelText("Full name"), "Taylor Example");
    await user.type(screen.getByLabelText("Business name"), "Example Marina");
    await user.type(screen.getByLabelText("Email"), "taylor@example.com");
    fireEvent.submit(button.closest("form")!);
    expect(fetch).not.toHaveBeenCalled();
    await user.click(consent);
    await user.click(button);
    expect(await screen.findByText(/Contact request received/)).toBeInTheDocument();
    const [url, options] = vi.mocked(fetch).mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/public\/leads$/);
    expect(options!.credentials).toBe("omit");
    expect(options!.headers).toEqual({ "Content-Type": "application/json" });
    expect(JSON.parse(options!.body as string)).toEqual({
      full_name: "Taylor Example", business_name: "Example Marina", email: "taylor@example.com",
      team_size: "solo", source: "intelligence-lab", contact_consent: true, marketing_consent: false,
    });
    expect(screen.getByText(/Referral permission is not requested or granted/)).toBeInTheDocument();
    expect(storage).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Email")).toHaveValue("");
  });

  it("submits marketing permission only when explicitly checked and reports contact failures", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(json({}, 503));
    render(<IntelligenceLabPage />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Full name"), "Taylor Example");
    await user.type(screen.getByLabelText("Business name"), "Example Marina");
    await user.type(screen.getByLabelText("Email"), "taylor@example.com");
    await user.click(screen.getByRole("checkbox", { name: /I consent to storing/ }));
    await user.click(screen.getByRole("checkbox", { name: /Optional: I separately/ }));
    await user.click(screen.getByRole("button", { name: "Send contact request" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("public service is unavailable");
    expect(JSON.parse(vi.mocked(fetch).mock.calls[0][1]!.body as string).marketing_consent).toBe(true);
    expect(screen.queryByText(/Contact request received/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toHaveValue("taylor@example.com");
  });
});
