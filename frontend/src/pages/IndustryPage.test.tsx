import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HashRouter, MemoryRouter, Route, Routes } from "react-router-dom";
import industries from "../lib/industries.json";
import { IndustryPage } from "./IndustryPage";

function renderPage(path = "/discover") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/discover" element={<IndustryPage />} />
        <Route path="/industries/:industry" element={<IndustryPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

async function fillLead() {
  await userEvent.type(screen.getByLabelText("Full name"), "Marine Visitor");
  await userEvent.type(screen.getByLabelText("Email for your requested response"), "visitor@example.com");
  await userEvent.type(screen.getByLabelText(/Which facility workflow/), "Improve slip scheduling");
  await userEvent.click(screen.getByLabelText("I request an email response from HarborIQ about this need."));
}

describe("Industry discovery", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows all industry destinations without requiring authentication", () => {
    renderPage();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("One Marine Industry. One Intelligent Platform.");
    for (const industry of industries) {
      expect(screen.getByRole("link", { name: new RegExp(`^${industry.label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`) }))
        .toHaveAttribute("href", `/industries/${industry.id}`);
    }
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each(industries)("personalizes $id pages and relevant prompts", (industry) => {
    renderPage(`/industries/${industry.id}`);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(industry.title);
    expect(screen.getByLabelText("What part of the marine industry are you in?")).toHaveValue(industry.id);
    expect(screen.getByLabelText(`Your ${industry.label} question`)).toHaveValue(industry.prompt);
    expect(screen.getByLabelText(industry.question)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: `Request a ${industry.label} conversation` })).toBeInTheDocument();
    expect(document.title).toBe(`${industry.label} | HarborIQ`);
  });

  it("changes content, question and conversion when the selector changes", async () => {
    renderPage("/industries/marinas");
    await userEvent.selectOptions(screen.getByLabelText("What part of the marine industry are you in?"), "marine-towing");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Operational intelligence for towing");
    expect(screen.getByLabelText("Your Marine Towing or Assistance question")).toHaveValue(industries[1].prompt);
    expect(screen.getByLabelText(/What nonemergency operational challenge/)).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("HarborIQ has not dispatched assistance");
    expect(screen.getByRole("note")).toHaveTextContent("VHF channel 16");
  });

  it("focuses a demo CTA without replacing a hash-router industry route", async () => {
    const scroll = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { value: scroll, configurable: true });
    window.location.hash = "#/industries/marinas";
    render(<HashRouter><Routes>
      <Route path="/industries/:industry" element={<IndustryPage />} />
    </Routes></HashRouter>);
    await userEvent.click(screen.getByRole("link", { name: "Explore Marina or Boatyard AI" }));
    expect(window.location.hash).toBe("#/industries/marinas");
    expect(document.getElementById("industry-demo")).toHaveFocus();
    expect(scroll).toHaveBeenCalled();
    window.location.hash = "";
    delete (HTMLElement.prototype as { scrollIntoView?: unknown }).scrollIntoView;
  });

  it("handles unsupported industry routes without inventing capabilities", () => {
    renderPage("/industries/imaginary");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Industry not found");
    expect(screen.queryByRole("button", { name: "Ask HarborIQ" })).not.toBeInTheDocument();
  });

  it("sends the selected industry to the real anonymous API and renders text safely", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({
      industry: "marinas",
      answer: "<script>alert('no')</script> Check occupancy records.",
      disclaimer: "Informational only.",
    }));
    renderPage("/industries/marinas");
    await userEvent.click(screen.getByRole("button", { name: "Ask HarborIQ" }));
    expect(await screen.findByRole("status")).toHaveTextContent("<script>alert('no')</script>");
    expect(document.querySelector("script")).toBeNull();
    const [url, options] = vi.mocked(fetch).mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/public\/demo$/);
    expect(options?.credentials).toBe("omit");
    expect(options?.headers).toEqual({ "Content-Type": "application/json" });
    expect(JSON.parse(options!.body as string)).toEqual({ industry: "marinas", prompt: industries[0].prompt });
  });

  it.each([503, 429, 502])("shows an honest error for demo HTTP %s, never a canned answer", async (status) => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ detail: "unavailable" }, status));
    renderPage("/industries/commercial-fishing");
    await userEvent.click(screen.getByRole("button", { name: "Ask HarborIQ" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("aborts an old sector request when the selection changes", async () => {
    vi.mocked(fetch).mockImplementationOnce((_url, options) => new Promise((_resolve, reject) => {
      options?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    }));
    renderPage("/industries/marinas");
    await userEvent.click(screen.getByRole("button", { name: "Ask HarborIQ" }));
    const oldSignal = vi.mocked(fetch).mock.calls[0][1]?.signal;
    await userEvent.selectOptions(screen.getByLabelText("What part of the marine industry are you in?"), "boat-owners");
    expect(oldSignal?.aborted).toBe(true);
    expect(screen.getByLabelText("Your Boat Owner question")).toHaveValue(industries[6].prompt);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("stores a classified conversation request without implicit marketing or partner sharing", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ ok: true, message: "Request received." }));
    renderPage("/industries/marinas");
    expect(screen.getByLabelText(/Optional: I also want/)).not.toBeChecked();
    expect(screen.getByLabelText("I request an email response from HarborIQ about this need.")).not.toBeChecked();
    await fillLead();
    await userEvent.click(screen.getByRole("button", { name: "Request a Marina or Boatyard conversation" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Request received.");
    const [url, options] = vi.mocked(fetch).mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/public\/leads$/);
    expect(JSON.parse(options!.body as string)).toEqual({
      full_name: "Marine Visitor", business_name: "Individual", email: "visitor@example.com",
      team_size: "solo", industry: "marinas", business_need: "Improve slip scheduling",
      product_interest: "operations", contact_requested: true, email_marketing_opt_in: false,
      source: "industry-discovery", website: "",
    });
    expect(screen.getByLabelText("Full name")).toHaveValue("");
  });

  it("captures marketing permission only when explicitly selected", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ ok: true, message: "Request received." }));
    renderPage("/industries/marinas");
    await fillLead();
    await userEvent.click(screen.getByLabelText(/Optional: I also want/));
    await userEvent.selectOptions(screen.getByLabelText("Product interest"), "partnership");
    await userEvent.click(screen.getByRole("button", { name: "Request a Marina or Boatyard conversation" }));
    await screen.findByRole("status");
    const body = JSON.parse(vi.mocked(fetch).mock.calls[0][1]!.body as string);
    expect(body.email_marketing_opt_in).toBe(true);
    expect(body.product_interest).toBe("partnership");
    expect(body).not.toHaveProperty("referral_authorized");
  });

  it("preserves input on failed lead capture", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({}, 503));
    renderPage("/industries/marinas");
    await fillLead();
    await userEvent.click(screen.getByRole("button", { name: "Request a Marina or Boatyard conversation" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("unavailable"));
    expect(screen.getByLabelText("Full name")).toHaveValue("Marine Visitor");
  });
});
