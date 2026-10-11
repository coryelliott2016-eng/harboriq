import { useEffect, useRef, useState, type MouseEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import industries from "../lib/industries.json";
import { PRIVACY_URL } from "../lib/marketingSite";
import { publicPost } from "../lib/publicApi";

type Industry = (typeof industries)[number];
type DemoResponse = { answer: string; industry: string; disclaimer: string };
type LeadResponse = { ok: boolean; message: string };

const fieldClass = "mt-2 w-full rounded-lg border border-slate-300 bg-white p-3 text-slate-900";
const buttonClass = "inline-block rounded-lg bg-indigo-700 px-5 py-3 font-semibold text-white hover:bg-indigo-800 disabled:opacity-50";

function jumpToSection(event: MouseEvent<HTMLAnchorElement>) {
  event.preventDefault();
  const target = document.getElementById(event.currentTarget.hash.slice(1));
  target?.scrollIntoView();
  target?.focus({ preventScroll: true });
}

function IndustryExperience({ industry }: { industry: Industry }) {
  const [prompt, setPrompt] = useState(industry.prompt);
  const [answer, setAnswer] = useState<DemoResponse | null>(null);
  const [demoError, setDemoError] = useState("");
  const [demoBusy, setDemoBusy] = useState(false);
  const [leadMessage, setLeadMessage] = useState("");
  const [leadError, setLeadError] = useState("");
  const [leadBusy, setLeadBusy] = useState(false);
  const demoRequest = useRef<AbortController | null>(null);
  const leadRequest = useRef<AbortController | null>(null);
  useEffect(() => () => {
    demoRequest.current?.abort();
    leadRequest.current?.abort();
  }, []);

  return (
    <div className="space-y-10">
      <section aria-labelledby="industry-title" className="rounded-2xl bg-white p-6 shadow-sm md:p-10">
        <p className="text-sm font-semibold text-indigo-700">{industry.label}</p>
        <h2 id="industry-title" className="mt-2 text-3xl font-bold">{industry.title}</h2>
        <p className="mt-4 max-w-3xl text-lg text-slate-600">{industry.summary}</p>
        <h3 className="mt-6 text-xl font-semibold">Relevant workflows to explore</h3>
        <ul className="mt-3 grid list-inside list-disc gap-3 md:grid-cols-2">
          {industry.capabilities.map((capability) => <li key={capability}>{capability}</li>)}
        </ul>
        <p className="mt-5 text-sm text-slate-600">
          Public AI provides informational guidance, not connected operational software.
          Existing service and marina workflows are available in the business application;
          other specialized modules and integrations are opportunities under evaluation.
        </p>
        <div className="mt-6 flex flex-wrap gap-4">
          <a className={buttonClass} href="#industry-demo" onClick={jumpToSection}>Explore {industry.label} AI</a>
          <a className="rounded-lg border border-indigo-700 px-5 py-3 font-semibold text-indigo-700" href="#industry-contact" onClick={jumpToSection}>
            Discuss {industry.label} needs
          </a>
          {(industry.id === "marine-service" || industry.id === "marinas") && (
            <Link className="px-5 py-3 font-semibold text-indigo-700" to="/signup">Explore the business application</Link>
          )}
        </div>
      </section>

      <section id="industry-demo" tabIndex={-1} aria-labelledby="demo-title" className="rounded-2xl bg-white p-6 shadow-sm md:p-10">
        <h2 id="demo-title" className="text-2xl font-bold">{industry.label} AI demonstration</h2>
        <p className="mt-3 text-slate-600">No account required. Your question is sent to our configured AI provider.
          Do not enter names, contact details, vessel identifiers, live locations, fishing grounds,
          confidential business information, claims or underwriting records.</p>
        <p role={industry.id === "marine-towing" ? "note" : undefined} className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-4 text-amber-950">
          Not an emergency or dispatch service. In immediate distress, contact local emergency services
          or the appropriate coast guard using VHF channel 16 where available. HarborIQ has not dispatched
          assistance and does not claim affiliation with Sea Tow or TowBoatUS.
        </p>
        <form className="mt-5" onSubmit={async (event) => {
          event.preventDefault();
          if (demoBusy || !prompt.trim()) return;
          setDemoBusy(true);
          setDemoError("");
          setAnswer(null);
          demoRequest.current = new AbortController();
          try {
            setAnswer(await publicPost<DemoResponse>("/public/demo", {
              industry: industry.id, prompt: prompt.trim(),
            }, demoRequest.current.signal));
          } catch (error) {
            setDemoError(error instanceof Error ? error.message : "The demo is unavailable.");
          } finally {
            setDemoBusy(false);
          }
        }}>
          <label htmlFor="demo-prompt" className="font-semibold">Your {industry.label} question</label>
          <textarea id="demo-prompt" className={fieldClass} rows={4} required maxLength={2000}
            value={prompt} onChange={(event) => setPrompt(event.target.value)} />
          <button className={`${buttonClass} mt-4`} disabled={demoBusy || !prompt.trim()} type="submit">
            {demoBusy ? "Asking HarborIQ…" : "Ask HarborIQ"}
          </button>
        </form>
        {demoError && <p className="mt-4 text-red-700" role="alert">{demoError}</p>}
        {answer && <div className="mt-5 rounded-lg bg-slate-50 p-5" role="status">
          <h3 className="font-semibold">AI-generated guidance — verify before acting</h3>
          <p className="mt-3 whitespace-pre-wrap">{answer.answer}</p>
          <p className="mt-4 text-sm text-slate-600">{answer.disclaimer}</p>
        </div>}
        <p className="mt-4 text-sm text-slate-600">Subject to usage limits and provider availability. No private customer
          records, operational tools or licensed knowledge retrieval are connected to this public demo.</p>
      </section>

      <section id="industry-contact" tabIndex={-1} aria-labelledby="contact-title" className="rounded-2xl bg-white p-6 shadow-sm md:p-10">
        <h2 id="contact-title" className="text-2xl font-bold">Discuss {industry.label} needs</h2>
        <p className="mt-3 text-slate-600">{industry.opportunity}</p>
        <p className="mt-3 text-sm text-slate-600">
          This requests a response from HarborIQ, Inc., not a partner introduction, service quote,
          booking or emergency assistance. No identifiable information is distributed to commercial partners.
        </p>
        <form className="mt-6 grid gap-5 md:grid-cols-2" onSubmit={async (event) => {
          event.preventDefault();
          if (leadBusy) return;
          const form = event.currentTarget;
          const data = new FormData(form);
          setLeadBusy(true);
          setLeadError("");
          setLeadMessage("");
          leadRequest.current = new AbortController();
          try {
            const result = await publicPost<LeadResponse>("/public/leads", {
              full_name: String(data.get("full_name") ?? "").trim(),
              business_name: String(data.get("business_name") ?? "").trim() || "Individual",
              email: String(data.get("email") ?? "").trim(),
              team_size: data.get("team_size"),
              industry: industry.id,
              business_need: String(data.get("business_need") ?? "").trim(),
              product_interest: data.get("product_interest"),
              contact_requested: data.get("contact_requested") === "on",
              email_marketing_opt_in: data.get("email_marketing_opt_in") === "on",
              source: "industry-discovery",
              website: data.get("website") ?? "",
            }, leadRequest.current.signal);
            setLeadMessage(result.message);
            form.reset();
          } catch (error) {
            setLeadError(error instanceof Error ? error.message : "Your request could not be completed.");
          } finally {
            setLeadBusy(false);
          }
        }}>
          <label>Full name
            <input className={fieldClass} name="full_name" autoComplete="name" required maxLength={120} />
          </label>
          <label>Business name (optional for individuals)
            <input className={fieldClass} name="business_name" autoComplete="organization" maxLength={160} />
          </label>
          <label>Email for your requested response
            <input className={fieldClass} name="email" type="email" autoComplete="email" required maxLength={254} />
          </label>
          <label>Team size
            <select className={fieldClass} name="team_size" defaultValue="solo">
              <option value="solo">Just me</option><option value="team">2–5 people</option>
              <option value="business">6–15 people</option><option value="enterprise">16+ people</option>
            </select>
          </label>
          <label>Product interest
            <select className={fieldClass} name="product_interest" defaultValue="operations">
              <option value="operations">Business operations</option>
              <option value="ai">AI capabilities</option>
              <option value="partnership">Partnership discussion</option>
            </select>
          </label>
          <label className="md:col-span-2">{industry.question}
            <textarea className={fieldClass} name="business_need" rows={3} required maxLength={2000} />
          </label>
          <label className="hidden" aria-hidden="true">Leave this field blank
            <input name="website" tabIndex={-1} autoComplete="off" />
          </label>
          <label className="flex items-start gap-3 md:col-span-2">
            <input className="mt-1" type="checkbox" name="contact_requested" required />
            <span>I request an email response from HarborIQ about this need.</span>
          </label>
          <label className="flex items-start gap-3 md:col-span-2">
            <input className="mt-1" type="checkbox" name="email_marketing_opt_in" />
            <span>Optional: I also want HarborIQ product and industry updates by email. This is not permission for partner data sharing.</span>
          </label>
          <p className="text-sm text-slate-600 md:col-span-2">
            Read our <a className="underline" href={PRIVACY_URL}>Privacy Policy</a>.
            Only share information you are authorized to provide. Choosing not to receive marketing does not affect your request.
          </p>
          <div className="md:col-span-2">
            <button type="submit" className={buttonClass} disabled={leadBusy}>
              {leadBusy ? "Sending…" : `Request a ${industry.label} conversation`}
            </button>
          </div>
        </form>
        {leadMessage && <p className="mt-4 text-green-800" role="status">{leadMessage}</p>}
        {leadError && <p className="mt-4 text-red-700" role="alert">{leadError}</p>}
      </section>
    </div>
  );
}

export function IndustryPage() {
  const { industry: slug } = useParams();
  const navigate = useNavigate();
  const industry = industries.find((item) => item.id === slug);
  const homepage = !slug;
  if (!homepage && !industry) {
    return <main className="mx-auto max-w-3xl p-10">
      <title>Industry not found | HarborIQ</title>
      <h1 className="text-3xl font-bold">Industry not found</h1>
      <Link className="mt-5 inline-block underline" to="/discover">Explore marine industries</Link>
    </main>;
  }
  return (
    <div className="min-h-screen bg-slate-100 text-slate-900">
      <title>{industry ? `${industry.label} | HarborIQ` : "HarborIQ | One Marine Industry. One Intelligent Platform."}</title>
      <meta name="description" content={industry?.summary ?? "AI-powered intelligence, business operations, and connected services for the people and businesses that power the marine industry."} />
      <a className="sr-only focus:not-sr-only focus:block focus:p-3" href="#industry-main" onClick={jumpToSection}>Skip to content</a>
      <header className="border-b border-slate-200 bg-white">
        <nav aria-label="Main navigation" className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 p-5">
          <Link to="/discover" className="text-2xl font-bold text-indigo-700">HarborIQ</Link>
          <div className="flex flex-wrap gap-5 font-semibold">
            <Link to="/discover">Industries</Link><Link to="/login">Business login</Link>
          </div>
        </nav>
      </header>
      <main id="industry-main" tabIndex={-1} className="mx-auto max-w-6xl space-y-10 px-5 py-10">
        <section>
          <p className="font-semibold text-indigo-700">HarborIQ, Inc. · The marine ecosystem</p>
          <h1 className="mt-3 max-w-4xl text-4xl font-bold leading-tight md:text-6xl">
            {homepage ? "One Marine Industry. One Intelligent Platform." : industry!.title}
          </h1>
          <p className="mt-5 max-w-4xl text-xl text-slate-600">
            AI-powered intelligence, business operations, and connected services for the people and businesses that power the marine industry.
          </p>
          <label htmlFor="industry-selector" className="mt-8 block text-lg font-semibold">What part of the marine industry are you in?</label>
          <select id="industry-selector" className={`${fieldClass} max-w-xl`} value={industry?.id ?? ""}
            onChange={(event) => navigate(`/industries/${event.target.value}`)}>
            <option value="" disabled>Select your industry</option>
            {industries.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
        </section>
        {industry ? <IndustryExperience key={industry.id} industry={industry} /> : (
          <section aria-label="Marine industries" className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
            {industries.map((item) => <Link key={item.id} to={`/industries/${item.id}`}
              className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm hover:border-indigo-500">
              <h2 className="text-xl font-bold text-indigo-700">{item.label}</h2>
              <p className="mt-3 text-slate-600">{item.summary}</p>
              <p className="mt-4 font-semibold">Explore your industry →</p>
            </Link>)}
          </section>
        )}
        <section aria-labelledby="shared-title" className="rounded-2xl bg-slate-900 p-7 text-white">
          <h2 id="shared-title" className="text-2xl font-bold">One shared intelligence foundation</h2>
          <p className="mt-4">Sector-specific demonstrations use one secure AI gateway, not separate AI systems.
            Guidance is AI-generated and requires verification. Specialized SaaS, premium AI, authorized partnerships
            and aggregated analytics are commercial opportunities, not promises of currently available integrations.</p>
          <p className="mt-4">Partner referrals and paid data products are not launched here. They require purpose-specific
            authorization, recipient disclosure, contractual review, validated data rights and effective privacy controls.</p>
        </section>
      </main>
      <footer className="mx-auto max-w-6xl p-5 text-sm text-slate-600">
        HarborIQ, Inc. · <a className="underline" href={PRIVACY_URL}>Privacy Policy</a> · <Link className="underline" to="/discover">Explore industries</Link>
      </footer>
    </div>
  );
}
