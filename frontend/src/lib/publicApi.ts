const API_URL = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");

export async function publicPost<T>(
  path: "/public/demo" | "/public/leads",
  body: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) controller.abort();
  const timeout = setTimeout(abort, 30_000);
  try {
    const response = await fetch(`${API_URL}/api/v1${path}`, {
      method: "POST",
      credentials: "omit",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!response.ok) {
      if (response.status === 429) throw new Error("Usage limit reached. Please try again later.");
      if (response.status === 503) throw new Error("This experience is currently unavailable. Please try again later.");
      throw new Error("Your request could not be completed. Please check your details and try again.");
    }
    return await response.json() as T;
  } catch (error) {
    if (controller.signal.aborted) throw new Error("The request was cancelled or timed out. Please try again.", { cause: error });
    if (error instanceof TypeError) throw new Error("Unable to connect. Please try again later.", { cause: error });
    throw error;
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", abort);
  }
}
