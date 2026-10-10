import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AiDemoPage, MarketingContactPage, MarketingHome, MarketingLayout } from "./MarketingPages";
import { setAnalyticsConsent } from "../lib/publicMarketing";
import MarketingApp from "./MarketingApp";

function response(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
}
function renderPage(page: React.ReactNode) {
  return render(<MemoryRouter><Routes><Route element={<MarketingLayout />}><Route path="/" element={page} /></Route></Routes></MemoryRouter>);
}
const available = { available: true, message: "Test engine fixture only", message_limit: 3, max_message_chars: 2000 };

describe("public marketing experience", () => {
  beforeEach(() => { vi.stubGlobal("fetch", vi.fn()); setAnalyticsConsent(false); });
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); setAnalyticsConsent(false); });

  it("offers public navigation, verified platform features, and an explicitly illustrative workflow", () => {
    renderPage(<MarketingHome />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Meet HarborIQ");
    expect(screen.getByRole("link", { name: /try harboriq ai/i })).toHaveAttribute("href", "/ai-demo");
    expect(screen.getByText(/illustrative synthetic example/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#marketing-content");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("navigates the public acquisition journey without sign-in or staff API requests", async () => {
    vi.mocked(fetch).mockResolvedValue(response({ ...available, available: false, message: "No engine configured." }));
    render(<MemoryRouter><MarketingApp /></MemoryRouter>);
    fireEvent.click(screen.getByRole("link", { name: /try harboriq ai/i }));
    await screen.findByText("Live AI unavailable");
    expect(document.activeElement).toBe(screen.getByRole("main"));
    fireEvent.click(screen.getByRole("link", { name: "Get Early Access" }));
    expect(screen.getByLabelText("Business email")).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.every(([url]) => String(url).includes("/public/ai-demo/status"))).toBe(true);
  });

  it("never imitates AI when unavailable, but lets visitors select and edit a suggested question", async () => {
    vi.mocked(fetch).mockResolvedValue(response({ ...available, available: false, message: "No verified inference engine is connected." }));
    renderPage(<AiDemoPage />);
    expect(await screen.findByText("Live AI unavailable")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /engine diagnostics/i }));
    expect((screen.getByLabelText("Your marine technical question") as HTMLTextAreaElement).value).toContain("Yamaha");
    expect(screen.getByRole("button", { name: "Ask HarborIQ" })).toBeDisabled();
    expect(screen.queryByRole("heading", { name: "HarborIQ", level: 3 })).not.toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("submits anonymously through the demo API and keeps its session quota when resetting", async () => {
    const mock = vi.mocked(fetch);
    mock.mockResolvedValueOnce(response(available))
      .mockResolvedValueOnce(response({ session_token: "test-session", expires_in: 600 }))
      .mockResolvedValueOnce(response({ answer: "Fixture only: gather observed symptoms.", remaining_messages: 2 }))
      .mockResolvedValueOnce(response({ answer: "Fixture follow-up.", remaining_messages: 1 }));
    renderPage(<AiDemoPage />);
    await screen.findByText("Live engine connected");
    fireEvent.change(screen.getByLabelText("Your marine technical question"), { target: { value: "Boat battery issue" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask HarborIQ" }));
    expect(await screen.findByText("Fixture only: gather observed symptoms.")).toBeInTheDocument();
    expect(mock.mock.calls[2][0]).toContain("/ai-demo/chat");
    const options = mock.mock.calls[2][1]!;
    expect(options.credentials).toBe("omit");
    expect(options.headers).not.toHaveProperty("Authorization");
    expect(JSON.parse(options.body as string)).toEqual({ session_token: "test-session", message: "Boat battery issue", history: [] });
    fireEvent.click(screen.getByRole("button", { name: "New conversation" }));
    expect(screen.queryByText("Fixture only: gather observed symptoms.")).not.toBeInTheDocument();
    expect(screen.getByText(/2 questions per session/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Your marine technical question"), { target: { value: "Follow up" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask HarborIQ" }));
    await screen.findByText("Fixture follow-up.");
    expect(mock).toHaveBeenCalledTimes(4);
  });

  it("shows service errors and never appends them as generated answers", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(response(available))
      .mockResolvedValueOnce(response({ session_token: "test-session", expires_in: 600 }))
      .mockResolvedValueOnce(response({ detail: "Live engine unavailable." }, 503));
    renderPage(<AiDemoPage />);
    await screen.findByText("Live engine connected");
    fireEvent.change(screen.getByLabelText("Your marine technical question"), { target: { value: "Engine issue" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask HarborIQ" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Live engine unavailable.");
    expect(screen.queryByRole("heading", { name: "HarborIQ", level: 3 })).not.toBeInTheDocument();
  });

  it("fails closed on malformed availability and permits retry", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(response({ available: "yes" })).mockResolvedValueOnce(response(available));
    renderPage(<AiDemoPage />);
    await screen.findByText("AI availability could not be verified.");
    expect(screen.getByRole("button", { name: "Ask HarborIQ" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Check availability again" }));
    await screen.findByText("Live engine connected");
  });

  it("does not submit contact details without consent and only confirms verified storage", async () => {
    vi.mocked(fetch).mockResolvedValue(response({ ok: true, id: "lead-fixture" }, 201));
    renderPage(<MarketingContactPage />);
    const button = screen.getByRole("button", { name: /request early access/i });
    expect(button).toBeDisabled();
    fireEvent.submit(button.closest("form")!);
    expect(fetch).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Sample Technician" } });
    fireEvent.change(screen.getByLabelText("Business name"), { target: { value: "Example Marine" } });
    fireEvent.change(screen.getByLabelText("Business email"), { target: { value: "tech@example.com" } });
    fireEvent.click(screen.getByLabelText(/I authorize HarborIQ/i));
    fireEvent.submit(button.closest("form")!);
    await screen.findByText("Your request was saved.");
    expect(screen.getByText(/email delivery and a meeting booking have not been confirmed/i)).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("does not show lead success on storage failure", async () => {
    vi.mocked(fetch).mockResolvedValue(response({ detail: "Lead storage unavailable." }, 503));
    renderPage(<MarketingContactPage />);
    fireEvent.click(screen.getByLabelText(/I authorize HarborIQ/i));
    fireEvent.submit(screen.getByRole("button", { name: /request early access/i }).closest("form")!);
    expect(await screen.findByRole("alert")).toHaveTextContent("Your request has not been confirmed.");
    expect(screen.queryByText("Your request was saved.")).not.toBeInTheDocument();
  });

  it("sends only allowlisted aggregate events after opt-in and stops on withdrawal", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 204 }));
    renderPage(<MarketingHome />);
    expect(fetch).not.toHaveBeenCalled();
    const checkbox = screen.getByLabelText(/allow anonymous, aggregate usage/i);
    fireEvent.click(checkbox);
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    expect(JSON.parse(vi.mocked(fetch).mock.calls[0][1]!.body as string)).toEqual({ event: "homepage_view", consent: true });
    fireEvent.click(checkbox);
    fireEvent.click(screen.getByRole("link", { name: "Get Early Access" }));
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
