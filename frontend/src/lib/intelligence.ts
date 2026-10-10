const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const PUBLIC_BASE = `${API_URL.replace(/\/$/, "")}/api/v1/public`;

export type IntelligenceSector = "service" | "marina";

export interface DemoSession {
  session_token: string;
  expires_at: string;
  requests_remaining: number;
}

export interface IntelligenceResult {
  mode: "live_public_data";
  sector: IntelligenceSector;
  summary: string;
  source_url: string;
  source_name: string;
  retrieved_at: string;
  observed_at: string;
  station: string;
  product: "water_level" | "currents";
  measurements: { time: string; value: string; unit: string }[];
  warnings: string[];
  requests_remaining: number;
}

export class PublicIntelligenceError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "PublicIntelligenceError";
    this.status = status;
  }
}

// The staff API helper includes cookies even for anonymous calls. This public
// transport deliberately never reads staff tokens, refreshes auth, or caches.
async function publicPost<T>(path: string, body: unknown, sessionToken?: string): Promise<T> {
  const response = await fetch(`${PUBLIC_BASE}${path}`, {
    method: "POST",
    credentials: "omit",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      ...(sessionToken ? { "X-Demo-Session": sessionToken } : {}),
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const messages: Record<number, string> = {
      401: "Demo session expired or is invalid. Restart the demo session.",
      403: "Demo session is not authorized. Restart the demo session.",
      410: "Demo session expired. Restart the demo session.",
      422: "The public request could not be validated. Check your selections.",
      429: "Request limit reached. Please wait before trying again.",
      502: "NOAA data is unavailable. No demonstration data was substituted.",
      503: "The public service is unavailable. Please try again later.",
      504: "NOAA data retrieval timed out. Please try again later.",
    };
    throw new PublicIntelligenceError(
      response.status,
      messages[response.status] ?? "The public request failed. Please try again later.",
    );
  }
  return response.json() as Promise<T>;
}

export function startDemoSession() {
  return publicPost<DemoSession>("/intelligence/sessions", { accepted_safety_notice: true });
}

export function requestIntelligence(sessionToken: string, sector: IntelligenceSector, station: string) {
  return publicPost<IntelligenceResult>(
    "/intelligence/assist",
    { sector, station, product: "water_level" },
    sessionToken,
  );
}

export function submitPilotContact(contact: {
  full_name: string;
  business_name: string;
  email: string;
  marketing_consent: boolean;
}) {
  return publicPost<unknown>("/leads", {
    ...contact,
    team_size: "solo",
    source: "intelligence-lab",
    contact_consent: true,
  });
}
