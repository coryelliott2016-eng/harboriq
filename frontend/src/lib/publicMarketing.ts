const base = `${(import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "")}/api/v1/public`;

export class PublicRequestError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

// Public requests intentionally omit staff tokens, cookies, and refresh behavior.
export async function publicRequest<T>(
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) controller.abort();
  const timer = setTimeout(abort, 25_000);
  try {
    const response = await fetch(`${base}${path}`, {
      method: body === undefined ? "GET" : "POST",
      credentials: "omit",
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
    if (response.status === 204) return undefined as T;
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const fallback = response.status === 429
        ? "Demo usage limit reached. Please try again later."
        : response.status === 503
          ? "This service is temporarily unavailable. Please try again later."
          : "The request could not be completed. Please check your details.";
      throw new PublicRequestError(
        typeof data?.detail === "string" ? data.detail : fallback,
        response.status,
      );
    }
    if (data === null) throw new Error("The service returned an invalid response.");
    return data as T;
  } catch (error) {
    if (controller.signal.aborted) {
      throw new Error("Request cancelled or timed out. Please try again.", { cause: error });
    }
    if (error instanceof TypeError) {
      throw new Error("Unable to connect to HarborIQ. Please check your connection and try again.", { cause: error });
    }
    if (error instanceof Error) throw error;
    throw new Error("Unable to connect. Please try again.", { cause: error });
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}

export type MarketingEvent =
  | "homepage_view" | "demo_launch" | "category_select" | "first_question"
  | "ai_response" | "demo_error" | "early_access_click" | "lead_submitted";

let analyticsConsent = false;
export function setAnalyticsConsent(value: boolean) {
  analyticsConsent = value;
}

export function trackMarketingEvent(event: MarketingEvent) {
  if (!analyticsConsent) return;
  void publicRequest<void>("/marketing-events", { event, consent: true }).catch(() => {
    // Measurement must never block the demo or lead capture.
  });
}

export interface DemoStatus {
  available: boolean;
  message: string;
  message_limit: number;
  max_message_chars: number;
}

export interface DemoMessage {
  role: "user" | "assistant";
  content: string;
}
