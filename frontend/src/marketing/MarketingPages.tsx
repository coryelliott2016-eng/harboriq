import { useEffect, useRef, useState } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import { PRIVACY_URL, TERMS_URL } from "../lib/marketingSite";
import {
  publicRequest, setAnalyticsConsent, trackMarketingEvent,
  type DemoMessage, type DemoStatus,
} from "../lib/publicMarketing";
import "./marketing.css";

const home = import.meta.env.VITE_SITE_MODE === "marketing" ? "/" : "/explore";
const capabilities = [
  ["Customers & vessels", "Keep customer contacts and vessel information alongside service work."],
  ["Jobs & dispatch", "Organize jobs, estimates, assignments, and technician schedules."],
  ["Technician workflows", "Use the field app for job notes, photos, signatures, and time tracking."],
  ["Reports & billing", "Review service operations and manage estimates, invoices, and payments."],
];
const scenarios = [
  { name: "Engine diagnostics", label: "Diagnostic assistance", prompt: "My Yamaha outboard cranks but won’t start. What information should I gather and what should I check first?" },
  { name: "Electrical systems", label: "Diagnostic assistance", prompt: "My boat’s batteries are charged, but the electronics keep restarting. What measurements would help narrow down the problem?" },
  { name: "Marine networking", label: "Diagnostic assistance", prompt: "My NMEA 2000 devices intermittently lose communication. What symptoms and network details should I record?" },
  { name: "Maintenance", label: "Synthetic records · no predictive model", prompt: "Illustrative synthetic profile: vessel Demo One; single outboard, model unknown; 97 recorded engine hours; sample service records: general inspection at 10 hours, routine service at 45 hours with procedures not recorded. What missing information should I gather before planning a 100-hour service? Do not predict failure or invent manufacturer-specific procedures." },
  { name: "Service operations", label: "Illustrative synthetic record · draft assistance", prompt: "Draft a service report from this fictional sample only: vessel Demo One; customer Example Marine; technician observed intermittent electronics restarts; battery voltage under load has not been measured; no diagnosis confirmed. Separate observations from proposed checks." },
  { name: "Ask HarborIQ", label: "Marine topics only", prompt: "My engine overheats at higher RPM but runs normally at idle. What follow-up information would you need before suggesting possible causes?" },
];

function PageMetadata({ title, description }: { title: string; description: string }) {
  const { pathname } = useLocation();
  useEffect(() => {
    const previousTitle = document.title;
    document.title = `${title} | HarborIQ`;
    const restore: (() => void)[] = [];
    for (const [name, content] of [
      ["description", description], ["og:title", document.title],
      ["og:description", description], ["og:type", "website"],
      ["twitter:card", "summary"],
    ]) {
      const attribute = name.startsWith("og:") ? "property" : "name";
      const existing = document.head.querySelector<HTMLMetaElement>(`meta[${attribute}="${name}"]`);
      const tag = existing ?? document.createElement("meta");
      const previous = tag.content;
      tag.setAttribute(attribute, name);
      tag.content = content;
      document.head.append(tag);
      restore.push(() => { if (existing) tag.content = previous; else tag.remove(); });
    }
    const origin = import.meta.env.VITE_PUBLIC_SITE_URL;
    if (origin && /^https:\/\/[^/]+\/?$/.test(origin)) {
      const existing = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]');
      const canonical = existing ?? document.createElement("link");
      const previous = canonical.href;
      canonical.rel = "canonical";
      canonical.href = `${origin.replace(/\/$/, "")}${pathname}`;
      document.head.append(canonical);
      restore.push(() => { if (existing) canonical.href = previous; else canonical.remove(); });
    }
    return () => {
      document.title = previousTitle;
      restore.forEach((reset) => reset());
    };
  }, [title, description, pathname]);
  return null;
}

export function MarketingLayout() {
  const [consent, setConsent] = useState(false);
  const { pathname } = useLocation();
  useEffect(() => () => setAnalyticsConsent(false), []);
  useEffect(() => {
    document.getElementById("marketing-content")?.focus();
  }, [pathname]);
  return (
    <div className="hi-marketing">
      <a className="hi-skip" href="#marketing-content">Skip to content</a>
      <header className="hi-header">
        <Link className="hi-brand" to={home} aria-label="HarborIQ home">
          <img src="/favicon.svg" alt="" width="32" height="32" />Harbor<span>IQ</span>
        </Link>
        <nav aria-label="Main navigation">
          <Link to={`${home}#platform`}>Platform</Link>
          <Link to="/ai-demo">AI Lab</Link>
          <Link to="/contact">Early access</Link>
          {import.meta.env.VITE_SITE_MODE !== "marketing" && <Link to="/login">Sign in</Link>}
        </nav>
      </header>
      <main id="marketing-content" tabIndex={-1}><Outlet /></main>
      <footer className="hi-footer">
        <div><strong>HarborIQ</strong><p>Marine service. Thoughtfully connected.</p></div>
        <nav aria-label="Legal navigation">
          <a href={PRIVACY_URL}>Privacy</a>
          <a href={TERMS_URL}>Terms</a>
          <Link to="/demo-disclosure">Demo limitations</Link>
          <Link to="/contact">Contact</Link>
        </nav>
        <label className="hi-consent">
          <input type="checkbox" checked={consent} onChange={(event) => {
            const enabled = event.target.checked;
            setConsent(enabled);
            setAnalyticsConsent(enabled);
            if (enabled) trackMarketingEvent(window.location.pathname === "/ai-demo" ? "demo_launch" : "homepage_view");
          }} />
          Allow anonymous, aggregate usage measurement for this visit. No chats or contact details are sent.
        </label>
      </footer>
    </div>
  );
}

export function MarketingHome() {
  const location = useLocation();
  useEffect(() => {
    trackMarketingEvent("homepage_view");
  }, []);
  useEffect(() => {
    if (location.hash === "#platform") document.getElementById("platform")?.scrollIntoView?.();
  }, [location.hash]);
  return (
    <>
      <PageMetadata title="Marine service software" description="Explore HarborIQ’s marine service workflows, vessel management, and public AI Lab." />
      <section className="hi-hero hi-container">
        <div>
          <p className="hi-eyebrow">Marine intelligence platform</p>
          <h1>Meet HarborIQ.<br /><span>The Intelligence Behind Smarter Marine Service.</span></h1>
          <p className="hi-lede">From complex engine diagnostics to service management, discover how AI-powered intelligence can help marine professionals work smarter.</p>
          <div className="hi-actions">
            <Link className="hi-button" to="/ai-demo">Try HarborIQ AI <span aria-hidden="true">↗</span></Link>
            <a className="hi-button hi-secondary" href="#platform">Explore the Platform</a>
          </div>
          <p className="hi-muted">Explore without registration. Live AI availability is shown in the Lab.</p>
        </div>
        <div className="hi-preview">
          <div className="hi-preview-top"><span className="hi-dot" />HarborIQ AI Lab</div>
          <p className="hi-eyebrow">Start with a real-world question</p>
          <blockquote>“My engine overheats at higher RPM but runs normally at idle. What should I check?”</blockquote>
          <p>No scripted diagnoses. The Lab only displays answers when a verified HarborIQ engine is connected.</p>
          <Link to="/ai-demo">Open the AI Lab <span aria-hidden="true">→</span></Link>
          <div className="hi-signal" aria-hidden="true"><i /><i /><i /><i /><i /><i /><i /></div>
        </div>
      </section>
      <section id="platform" className="hi-section hi-container">
        <p className="hi-eyebrow">The platform</p>
        <h2>Less disconnected work.<br />More clarity from intake to invoice.</h2>
        <p className="hi-section-intro">Explore workflows implemented in HarborIQ’s authenticated platform. Your business records remain behind sign-in; this public preview uses no customer data.</p>
        <div className="hi-grid">
          {capabilities.map(([name, description], index) => <article className="hi-card" key={name}>
            <span className="hi-card-number">0{index + 1}</span><h3>{name}</h3><p>{description}</p>
          </article>)}
        </div>
        <details className="hi-product-preview">
          <summary>Explore a sample service workflow</summary>
          <p className="hi-muted">Illustrative synthetic example · not a live customer job</p>
          <ol className="hi-workflow">
            <li><strong>Customer problem</strong><p>Demo One reports intermittent electronics restarts.</p></li>
            <li><strong>Diagnostic assistance</strong><p>Record symptoms and measurements. AI assistance is pending a verified engine connection.</p></li>
            <li><strong>Service workflow</strong><p>Organize an inspection job and assign a technician in the authenticated platform.</p></li>
            <li><strong>Documentation</strong><p>Capture observations, time, and supporting photos.</p></li>
            <li><strong>Completed job</strong><p>Review verified findings and prepare an invoice.</p></li>
          </ol>
        </details>
      </section>
      <section className="hi-section hi-container hi-audience">
        <p className="hi-eyebrow">Built around marine service</p>
        <h2>For the people who keep vessels moving.</h2>
        <p>Mobile technicians · Independent repair businesses · Service departments · Marinas · Fleet service operators · Outboard and inboard specialists</p>
        <p>HarborIQ brings together customers, vessels, jobs, and service documentation. Live diagnostic intelligence and predictive maintenance are not currently available.</p>
      </section>
      <section className="hi-section hi-container hi-cta">
        <p className="hi-eyebrow">Your next step</p>
        <h2>Imagine what a connected service workflow could do for your business.</h2>
        <p>No unapproved pricing plans. Tell us what your operation needs and request early access or a personalized demonstration.</p>
        <Link className="hi-button" to="/contact" onClick={() => trackMarketingEvent("early_access_click")}>Get Early Access</Link>
      </section>
    </>
  );
}

export function AiDemoPage() {
  const [status, setStatus] = useState<DemoStatus | null>(null);
  const [statusError, setStatusError] = useState("");
  const [message, setMessage] = useState("");
  const [history, setHistory] = useState<DemoMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [remaining, setRemaining] = useState<number | null>(null);
  const [category, setCategory] = useState(0);
  const session = useRef<{ session_token: string; expires_at: number } | null>(null);
  const active = useRef<AbortController | null>(null);
  const firstQuestion = useRef(false);
  const input = useRef<HTMLTextAreaElement>(null);

  function checkStatus(signal?: AbortSignal) {
    return publicRequest<DemoStatus>("/ai-demo/status", undefined, signal).then((result) => {
      if (signal?.aborted) return;
      if (typeof result.available !== "boolean" || !Number.isInteger(result.max_message_chars)
        || result.max_message_chars < 1 || result.max_message_chars > 10000
        || !Number.isInteger(result.message_limit) || result.message_limit < 1 || typeof result.message !== "string") {
        throw new Error("AI availability could not be verified.");
      }
      setStatus(result);
      setStatusError("");
    }).catch((failure: unknown) => {
      if (signal?.aborted) return;
      setStatus(null);
      setStatusError(failure instanceof Error ? failure.message : "AI availability could not be verified.");
    });
  }
  useEffect(() => {
    const controller = new AbortController();
    void checkStatus(controller.signal);
    trackMarketingEvent("demo_launch");
    return () => { controller.abort(); active.current?.abort(); };
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy || !status?.available || !message.trim() || remaining === 0) return;
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setError("");
    try {
      if (!session.current || session.current.expires_at <= Date.now()) {
        const created = await publicRequest<{ session_token: string; expires_in: number }>("/ai-demo/session", {}, controller.signal);
        if (typeof created.session_token !== "string" || !Number.isFinite(created.expires_in)) {
          throw new Error("Unable to establish a demo session.");
        }
        session.current = { session_token: created.session_token, expires_at: Date.now() + created.expires_in * 1000 };
      }
      const question = message.trim();
      if (!firstQuestion.current) { trackMarketingEvent("first_question"); firstQuestion.current = true; }
      const result = await publicRequest<{ answer: string; remaining_messages: number }>("/ai-demo/chat", {
        session_token: session.current.session_token, message: question, history: history.slice(-6),
      }, controller.signal);
      if (controller.signal.aborted) return;
      if (typeof result.answer !== "string" || !result.answer.trim() || result.answer.length > 16000
        || !Number.isInteger(result.remaining_messages) || result.remaining_messages < 0) {
        throw new Error("The AI service returned an invalid response.");
      }
      setHistory((previous) => [...previous, { role: "user", content: question }, { role: "assistant", content: result.answer }]);
      setRemaining(result.remaining_messages);
      setMessage("");
      trackMarketingEvent("ai_response");
    } catch (failure) {
      if (!controller.signal.aborted) {
        setError(failure instanceof Error ? failure.message : "Unable to connect to the AI service.");
        trackMarketingEvent("demo_error");
      }
    } finally {
      if (active.current === controller) { setBusy(false); active.current = null; }
    }
  }
  return (
    <section className="hi-container hi-section">
      <PageMetadata title="AI Lab — Experience Marine Intelligence" description="Explore marine diagnostic scenarios in HarborIQ’s public AI Lab. Live engine availability is clearly identified." />
      <p className="hi-eyebrow">Explore without registration</p>
      <h1>HarborIQ AI Lab<br /><span>Experience Marine Intelligence.</span></h1>
      <p className="hi-lede">Ask a technical question. Separate observations from possible causes, and keep safety first.</p>
      <div className="hi-availability" role="status">
        {status ? <><strong>{status.available ? "Live engine connected" : "Live AI unavailable"}</strong><p>{status.message}</p></>
          : <p>{statusError || "Checking AI availability…"}</p>}
        <button className="hi-text-button" onClick={() => void checkStatus()}>Check availability again</button>
      </div>
      <div className="hi-lab-grid">
        <aside className="hi-scenarios" aria-label="Guided scenarios">
          <h2>Choose a starting point</h2>
          {scenarios.map((scenario, index) => <button
            key={scenario.name} aria-pressed={category === index} disabled={busy}
            onClick={() => {
              setCategory(index); setMessage(scenario.prompt); input.current?.focus();
              trackMarketingEvent("category_select");
            }}
          >{scenario.name}<small>{scenario.label}</small></button>)}
          <p className="hi-muted">Scenarios are suggested questions, not pre-written AI answers. Predictive maintenance is not implemented or validated.</p>
        </aside>
        <div className="hi-chat">
          <div className="hi-chat-top"><h2>Ask HarborIQ</h2>
            <button className="hi-text-button" onClick={() => {
              active.current?.abort(); active.current = null; setBusy(false);
              setHistory([]); setMessage(""); setError(""); input.current?.focus();
            }}>New conversation</button>
          </div>
          <p className="hi-muted">Read-only public demo · no access to vessel records or business tools · {remaining ?? status?.message_limit ?? "Limited"} questions per session. Resetting the conversation does not reset your quota.</p>
          <div className="hi-transcript" role="log" aria-label="Conversation" aria-live="polite" aria-relevant="additions" aria-busy={busy}>
            {history.length === 0 && <div className="hi-empty">
              <span aria-hidden="true">↗</span><h3>Start with the symptoms.</h3>
              <p>Describe the equipment, what changed, and what you observed. Never include customer details or sensitive information.</p>
              <p>When the live engine is unavailable, no generated answer is displayed.</p>
            </div>}
            {history.map((entry, index) => <article key={index} className={`hi-message hi-message-${entry.role}`}>
              <h3>{entry.role === "user" ? "You" : "HarborIQ"}</h3><p>{entry.content}</p>
            </article>)}
          </div>
          <form onSubmit={submit}>
            <label htmlFor="demo-question">Your marine technical question</label>
            <textarea id="demo-question" ref={input} rows={4} maxLength={status?.max_message_chars ?? 2000}
              value={message} onChange={(event) => setMessage(event.target.value)} disabled={busy}
              aria-describedby="demo-safety demo-limit" placeholder="Describe a symptom or choose a scenario…" />
            <p id="demo-limit" className="hi-muted">{message.length}/{status?.max_message_chars ?? 2000} characters</p>
            <div className="hi-actions">
              <button className="hi-button" disabled={busy || !status?.available || !message.trim() || remaining === 0}>
                {busy ? "Waiting for HarborIQ…" : "Ask HarborIQ"}
              </button>
              {busy && <button className="hi-text-button" type="button" onClick={() => {
                active.current?.abort(); active.current = null; setBusy(false); setError("Request cancelled. No answer was received.");
              }}>Cancel request</button>}
            </div>
            {error && <p className="hi-error" role="alert">{error}</p>}
          </form>
          <p id="demo-safety" className="hi-safety">AI assistance is not a confirmed diagnosis or a substitute for qualified inspection. Stop operation if unsafe. Follow verified manufacturer documentation; do not attempt hazardous testing. <Link to="/demo-disclosure">Read demo limitations</Link>.</p>
        </div>
      </div>
      <div className="hi-cta hi-section">
        <h2>Connect your service workflow.</h2>
        <p>Want to organize actual vessel records, jobs, and technicians? Request a personalized platform demonstration.</p>
        <Link className="hi-button" to="/contact" onClick={() => trackMarketingEvent("early_access_click")}>Get Early Access</Link>
      </div>
    </section>
  );
}

export function MarketingContactPage() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [consent, setConsent] = useState(false);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !consent) return;
    const data = new FormData(event.currentTarget);
    setBusy(true); setError("");
    try {
      const result = await publicRequest<{ ok: boolean; id: string }>("/leads", {
        full_name: data.get("full_name"), business_name: data.get("business_name"),
        email: data.get("email"), team_size: data.get("team_size"),
        source: "marketing-ai-lab", website: data.get("website") ?? "",
      });
      if (result.ok !== true || typeof result.id !== "string" || !result.id.trim()) {
        throw new Error("We could not verify that your request was saved.");
      }
      setSaved(true); trackMarketingEvent("lead_submitted");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Your request could not be saved.");
    } finally { setBusy(false); }
  }
  return (
    <section className="hi-container hi-section hi-contact">
      <PageMetadata title="Contact & early access" description="Request early access or a personalized HarborIQ marine service platform demonstration." />
      <p className="hi-eyebrow">Let’s talk marine service</p>
      <h1>Build a clearer<br /><span>service workflow.</span></h1>
      <p className="hi-lede">Request early access or a personalized demo. Pricing and launch availability will be discussed directly, not guessed here.</p>
      {saved ? <div className="hi-availability" role="status"><h2>Your request was saved.</h2><p>Email delivery and a meeting booking have not been confirmed. No meeting has been scheduled automatically.</p><Link to="/ai-demo">Explore the AI Lab</Link></div> : <form className="hi-lead-form" onSubmit={submit}>
        <label htmlFor="lead-name">Name</label><input id="lead-name" name="full_name" autoComplete="name" required maxLength={120} disabled={busy} />
        <label htmlFor="lead-business">Business name</label><input id="lead-business" name="business_name" autoComplete="organization" required maxLength={160} disabled={busy} />
        <label htmlFor="lead-email">Business email</label><input id="lead-email" name="email" type="email" autoComplete="email" required maxLength={254} disabled={busy} />
        <label htmlFor="lead-size">Operation size</label><select id="lead-size" name="team_size" disabled={busy}>
          <option value="solo">Independent technician</option><option value="team">Small team</option>
          <option value="business">Service business or marina</option><option value="enterprise">Fleet or multi-location operation</option>
        </select>
        <div className="hi-honeypot" aria-hidden="true"><label htmlFor="lead-website">Leave this field empty</label><input id="lead-website" name="website" tabIndex={-1} autoComplete="off" /></div>
        <label className="hi-consent"><input type="checkbox" checked={consent} required disabled={busy}
          onChange={(event) => setConsent(event.target.checked)} />
          I authorize HarborIQ to use these details to respond to this inquiry. This is not a marketing subscription.
        </label>
        <p className="hi-muted">Your contact details are submitted to HarborIQ’s lead system. Please review the <a href={PRIVACY_URL}>Privacy Policy</a>. Do not submit vessel, customer, payment, or other sensitive records.</p>
        <button className="hi-button" disabled={busy || !consent}>{busy ? "Submitting…" : "Request Early Access / Demo"}</button>
        {error && <p className="hi-error" role="alert">{error} Your request has not been confirmed.</p>}
      </form>}
    </section>
  );
}

export function DemoDisclosurePage() {
  return <section className="hi-container hi-section hi-disclosure">
    <PageMetadata title="AI demo limitations" description="Availability, privacy, safety, and usage limitations for HarborIQ’s public AI demonstration." />
    <p className="hi-eyebrow">Technical transparency</p><h1>Demo limitations</h1>
    <h2>Availability</h2><p>This repository does not currently contain a verified AI inference engine, retrieval service, or predictive model. The public API reports live AI unavailable and does not generate an imitation answer. Suggested scenarios and the synthetic service workflow are illustrative only.</p>
    <h2>Privacy & isolation</h2><p>The demo has no customer database access or business tools. Do not enter personal, confidential, or customer information. The current unavailable endpoint does not persist question text or send it for model training. Hosting infrastructure may retain request metadata; operational privacy and retention policies require review before release.</p>
    <h2>Usage</h2><p>Anonymous sessions expire. Session, IP, and shared quotas protect usage, and requests fail closed when enforcement is unavailable. Starting a new conversation clears this page’s transcript, not its server-side quota. Technical assistance must be limited to marine topics when an engine is connected.</p>
    <h2>Safety</h2><p>Potential causes are not confirmed diagnoses. Manufacturer specifications, service bulletins, and maintenance procedures must be verified against authorized sources. Seek qualified assistance for fuel, high-current electrical systems, rotating machinery, and other hazardous work.</p>
    <h2>Product & commercial status</h2><p>Customer, vessel, job, dispatch, reporting, and billing workflows are implemented in the authenticated application. This does not certify production readiness. Pricing, AI provider integration, approved knowledge resources, and legal review remain release prerequisites.</p>
    <Link className="hi-button" to="/ai-demo">Back to the AI Lab</Link>
  </section>;
}
