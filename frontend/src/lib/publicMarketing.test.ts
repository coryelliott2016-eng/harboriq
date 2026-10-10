import { afterEach, describe, expect, it, vi } from "vitest";
import { publicRequest } from "./publicMarketing";

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("public API transport", () => {
  it("accepts the aggregate analytics no-content response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(publicRequest<void>("/marketing-events", { event: "demo_launch", consent: true })).resolves.toBeUndefined();
  });
  it("times out hung public requests", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_url, options) => new Promise((_resolve, reject) => {
      options.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    })));
    const result = expect(publicRequest("/ai-demo/status")).rejects.toThrow(/timed out/i);
    await vi.advanceTimersByTimeAsync(25_001);
    await result;
  });

  it("returns a safe error for invalid JSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("not json", { status: 200 })));
    await expect(publicRequest("/ai-demo/status")).rejects.toThrow("invalid response");
  });

  it("handles rate limits without authentication refresh", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("not json", { status: 429 })));
    await expect(publicRequest("/ai-demo/chat", {})).rejects.toThrow(/usage limit/i);
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
