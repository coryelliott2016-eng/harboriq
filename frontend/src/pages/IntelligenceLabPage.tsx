import { useEffect, useState, type FormEvent } from "react";
import {
  PublicIntelligenceError,
  requestIntelligence,
  startDemoSession,
  submitPilotContact,
  type DemoSession,
  type IntelligenceResult,
  type IntelligenceSector,
} from "../lib/intelligence";

const inputClass = "mt-1 block w-full rounded-md border border-slate-300 bg-white px-3 py-2";
const buttonClass = "rounded-md bg-slate-900 px-4 py-2 font-medium text-white disabled:opacity-50";

function sourceHref(source: string): string | undefined {
  try {
    const url = new URL(source);
    if (url.protocol === "https:" && (url.hostname === "noaa.gov" || url.hostname.endsWith(".noaa.gov"))) {
      return url.href;
    }
  } catch {
    // Invalid source links remain plain text rather than becoming active URLs.
  }
  return undefined;
}

export function IntelligenceLabPage() {
  const [sector, setSector] = useState<IntelligenceSector>("service");
  const [station, setStation] = useState("8726520");
  const [safetyConsent, setSafetyConsent] = useState(false);
  const [session, setSession] = useState<DemoSession | null>(null);
  const [expired, setExpired] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<IntelligenceResult | null>(null);
  const [contactConsent, setContactConsent] = useState(false);
  const [marketingConsent, setMarketingConsent] = useState(false);
  const [contactBusy, setContactBusy] = useState(false);
  const [contactStatus, setContactStatus] = useState("");
  const [contactError, setContactError] = useState("");

  useEffect(() => {
    if (!session) return;
    const timer = window.setTimeout(
      () => {
        setExpired(true);
        setResult(null);
      },
      Math.max(0, Date.parse(session.expires_at) - Date.now()),
    );
    return () => window.clearTimeout(timer);
  }, [session]);

  async function runDemo(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!safetyConsent || busy || expired) return;
    setBusy(true);
    setError("");
    setResult(null);
    let assistStarted = false;
    try {
      const activeSession = session ?? await startDemoSession();
      setSession(activeSession);
      if (Date.parse(activeSession.expires_at) <= Date.now()) {
        setExpired(true);
        return;
      }
      if (activeSession.requests_remaining <= 0) return;
      assistStarted = true;
      const response = await requestIntelligence(activeSession.session_token, sector, station);
      setResult(response);
      setSession({ ...activeSession, requests_remaining: response.requests_remaining });
    } catch (err) {
      setError(err instanceof Error ? err.message : "The public request failed.");
      if (err instanceof PublicIntelligenceError && [401, 403, 410].includes(err.status)) {
        setSession(null);
        setExpired(true);
      } else if (assistStarted && err instanceof PublicIntelligenceError) {
        if (err.status === 429) {
          setSession((current) => current ? { ...current, requests_remaining: 0 } : null);
        } else if ([502, 504].includes(err.status)) {
          setSession((current) => current ? { ...current, requests_remaining: Math.max(0, current.requests_remaining - 1) } : null);
        }
      }
    } finally {
      setBusy(false);
    }
  }

  function restart() {
    setSession(null);
    setExpired(false);
    setResult(null);
    setError("");
    setSafetyConsent(false);
  }

  async function sendContact(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!contactConsent || contactBusy) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    setContactBusy(true);
    setContactStatus("");
    setContactError("");
    try {
      await submitPilotContact({
        full_name: String(fields.get("full_name")).trim(),
        business_name: String(fields.get("business_name")).trim(),
        email: String(fields.get("email")).trim(),
        marketing_consent: marketingConsent,
      });
      setContactStatus("Contact request received. This does not enroll you in a pilot or grant referral permission.");
      form.reset();
      setContactConsent(false);
      setMarketingConsent(false);
    } catch (err) {
      setContactError(err instanceof Error ? err.message : "Contact request failed.");
    } finally {
      setContactBusy(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-50 px-4 py-10 text-slate-900">
      <div className="mx-auto max-w-3xl space-y-8">
        <header className="space-y-3">
          <p className="text-sm font-semibold text-slate-600">HarborIQ · Public demonstration</p>
          <h1 className="text-3xl font-bold">Service / Marina Intelligence Lab</h1>
          <p>Explore a deterministic NOAA public-data demonstration. This is not generative AI, equipment diagnostics, or a connection to your HarborIQ tenant.</p>
          <p className="rounded-md border border-amber-300 bg-amber-50 p-4">
            Not for navigation, emergencies, or safety-critical decisions. Data may be delayed, incomplete, or unavailable.
            NOAA attribution is not an endorsement of HarborIQ. No simulated data is substituted.
          </p>
          <p className="text-sm text-slate-600">No account or contact request is required. Demo tokens stay in page memory only; no prompts, personal information, or tokens are saved to browser storage.</p>
        </header>

        <section aria-labelledby="demo-heading" className="space-y-4 rounded-lg border border-slate-200 bg-white p-6">
          <h2 id="demo-heading" className="text-xl font-semibold">Try live public data</h2>
          <form onSubmit={runDemo} className="space-y-4">
            <label className="block" htmlFor="lab-sector">Sector
              <select id="lab-sector" value={sector} onChange={(event) => setSector(event.target.value as IntelligenceSector)} disabled={busy} className={inputClass}>
                <option value="service">Service</option>
                <option value="marina">Marina</option>
              </select>
            </label>
            <label className="block" htmlFor="lab-station">NOAA water-level station
              <select id="lab-station" value={station} onChange={(event) => setStation(event.target.value)} disabled={busy} className={inputClass}>
                <option value="8726520">St Petersburg · 8726520</option>
                <option value="8518750">The Battery · 8518750</option>
                <option value="9414290">San Francisco · 9414290</option>
              </select>
            </label>
            <p>Product: water level. Currents are not offered in this demonstration.</p>
            <label className="flex items-start gap-2">
              <input type="checkbox" required checked={safetyConsent} onChange={(event) => setSafetyConsent(event.target.checked)} disabled={busy} className="mt-1" />
              I accept the safety notice: this demonstration is not for navigation, emergencies, or diagnostics.
            </label>
            <button className={buttonClass} type="submit" disabled={!safetyConsent || busy || expired || session?.requests_remaining === 0}>
              {busy ? "Retrieving NOAA data…" : session ? "Retrieve NOAA water level" : "Start demo and retrieve NOAA water level"}
            </button>
          </form>
          <div role="status" aria-live="polite">
            {busy ? "Request in progress." : expired ? "Demo session expired. Restart to continue." : session ? "Demo session active." : "Demo session not started."}
            {session && <p>Requests remaining: {session.requests_remaining} (last reported). Failed retrievals may also consume quota. Session expires: <time dateTime={session.expires_at}>{session.expires_at}</time></p>}
            {session?.requests_remaining === 0 && <p>Demo quota exhausted. Please wait before starting another session.</p>}
          </div>
          {error && <p role="alert" className="text-red-700">{error}</p>}
          {(session || expired) && <button type="button" disabled={busy} onClick={restart} className="rounded-md border border-slate-300 px-4 py-2">Restart demo session</button>}
        </section>

        {result && !expired && (
          <section aria-labelledby="result-heading" className="space-y-3 rounded-lg border border-slate-200 bg-white p-6">
            <h2 id="result-heading" className="text-xl font-semibold">Live public data · deterministic NOAA result</h2>
            <p>{result.summary}</p>
            <p>Sector: {result.sector === "marina" ? "Marina" : "Service"} · Station: {result.station} · Product: {result.product}</p>
            <p>Source: <a href={sourceHref(result.source_url)} target="_blank" rel="noopener noreferrer" className="underline">{result.source_name}</a></p>
            <p className="break-all">{result.source_url}</p>
            <p>Retrieved at: <time dateTime={result.retrieved_at}>{result.retrieved_at}</time></p>
            <p>Observed at: <time dateTime={result.observed_at}>{result.observed_at}</time></p>
            <h3 className="font-semibold">Warnings</h3>
            {result.warnings.length ? <ul className="list-disc pl-5">{result.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul> : <p>No additional source warnings reported. The safety notice still applies.</p>}
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <caption className="text-left font-semibold">NOAA measurements (source times as reported)</caption>
                <thead><tr><th scope="col">Time</th><th scope="col">Value</th><th scope="col">Unit</th></tr></thead>
                <tbody>{result.measurements.map((measurement, index) => <tr key={index}><td>{measurement.time}</td><td>{measurement.value}</td><td>{measurement.unit}</td></tr>)}</tbody>
              </table>
            </div>
          </section>
        )}

        <section aria-labelledby="contact-heading" className="space-y-4 rounded-lg border border-slate-200 bg-white p-6">
          <h2 id="contact-heading" className="text-xl font-semibold">Optional pilot / contact request</h2>
          <p>This is separate from the demonstration. Do not include customer records, equipment identifiers, or other sensitive information. Contact consent does not grant marketing or referral permission.</p>
          <form onSubmit={sendContact} className="space-y-4">
            <label className="block" htmlFor="lab-name">Full name<input id="lab-name" name="full_name" autoComplete="name" required maxLength={120} className={inputClass} /></label>
            <label className="block" htmlFor="lab-business">Business name<input id="lab-business" name="business_name" autoComplete="organization" required maxLength={160} className={inputClass} /></label>
            <label className="block" htmlFor="lab-email">Email<input id="lab-email" name="email" type="email" autoComplete="email" required maxLength={254} className={inputClass} /></label>
            <label className="flex items-start gap-2"><input type="checkbox" required checked={contactConsent} onChange={(event) => setContactConsent(event.target.checked)} className="mt-1" />I consent to storing these contact details and being contacted about this request.</label>
            <label className="flex items-start gap-2"><input type="checkbox" checked={marketingConsent} onChange={(event) => setMarketingConsent(event.target.checked)} className="mt-1" />Optional: I separately opt in to marketing communications.</label>
            <p className="text-sm">Referral permission is not requested or granted by this form.</p>
            <button type="submit" className={buttonClass} disabled={!contactConsent || contactBusy}>{contactBusy ? "Sending contact request…" : "Send contact request"}</button>
          </form>
          {contactStatus && <p role="status">{contactStatus}</p>}
          {contactError && <p role="alert" className="text-red-700">{contactError}</p>}
        </section>
      </div>
    </main>
  );
}
