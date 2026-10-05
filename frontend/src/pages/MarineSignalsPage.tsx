import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "../context/auth";
import { marineSignalsApi } from "../lib/services";
import type {
  MarineSignal,
  MarineSignalCategory,
  MarineSignalProfile,
} from "../types/api";
import { Badge, Button, Card, ErrorBanner, Field, Spinner, StatCard, inputClass } from "../components/ui";

const categories: { value: MarineSignalCategory; label: string }[] = [
  { value: "weather", label: "Weather & sea conditions" },
  { value: "environment", label: "Environment" },
  { value: "safety_recall", label: "Safety & recalls" },
  { value: "regulation", label: "Regulations" },
  { value: "season", label: "Seasons & calendars" },
  { value: "training", label: "Training" },
  { value: "fuel", label: "Fuel prices" },
  { value: "market", label: "Local demand & market" },
];

const emptyProfile: MarineSignalProfile = {
  service_area: "",
  specialties: [],
  interests: [],
  digest_email: null,
  digest_enabled: false,
  updated_at: null,
};

function localDate(value: string | null) {
  return value ? new Date(value).toLocaleString() : "Not checked yet";
}

export function MarineSignalsPage() {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const isAdmin = user?.role === "owner" || user?.role === "admin";
  const [profile, setProfile] = useState<MarineSignalProfile>(emptyProfile);
  const [specialtiesText, setSpecialtiesText] = useState("");
  const [sourceForm, setSourceForm] = useState({
    name: "",
    category: "weather" as MarineSignalCategory,
    source_url: "",
    feed_url: "",
    terms_url: "",
    terms_confirmed: false,
  });
  const [newSignal, setNewSignal] = useState({
    source_id: "",
    category: "weather" as MarineSignalCategory,
    title: "",
    citation_url: "",
    geography: "",
  });
  const [reviewing, setReviewing] = useState<MarineSignal | null>(null);
  const [reviewFields, setReviewFields] = useState({
    summary: "",
    why_it_matters: "",
    suggested_action: "",
    uncertainty: "",
    geography: "",
    priority: "normal" as "normal" | "urgent",
  });
  const [error, setError] = useState("");

  const sourcesQuery = useQuery({
    queryKey: ["marine-signals", "sources"],
    queryFn: marineSignalsApi.sources,
    refetchInterval: 5 * 60 * 1000,
  });
  const signalsQuery = useQuery({
    queryKey: ["marine-signals", "signals"],
    queryFn: () => marineSignalsApi.signals(true),
    refetchInterval: 5 * 60 * 1000,
  });
  const metricsQuery = useQuery({
    queryKey: ["marine-signals", "metrics"],
    queryFn: marineSignalsApi.metrics,
    refetchInterval: 5 * 60 * 1000,
  });
  const profileQuery = useQuery({
    queryKey: ["marine-signals", "profile"],
    queryFn: marineSignalsApi.profile,
  });

  useEffect(() => {
    if (profileQuery.data) {
      setProfile(profileQuery.data);
      setSpecialtiesText(profileQuery.data.specialties.join(", "));
    }
  }, [profileQuery.data]);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["marine-signals"] });
  };
  const sourceMutation = useMutation({
    mutationFn: marineSignalsApi.createSource,
    onSuccess: () => {
      setError("");
      setSourceForm({ ...sourceForm, name: "", source_url: "", feed_url: "", terms_url: "", terms_confirmed: false });
      refresh();
    },
    onError: (reason) => setError(reason instanceof Error ? reason.message : "Could not add source."),
  });
  const toggleSourceMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      marineSignalsApi.setSourceEnabled(id, enabled),
    onSuccess: refresh,
    onError: (reason) => setError(reason instanceof Error ? reason.message : "Could not update source."),
  });
  const profileMutation = useMutation({
    mutationFn: marineSignalsApi.saveProfile,
    onSuccess: (saved) => {
      setProfile(saved);
      setSpecialtiesText(saved.specialties.join(", "));
      setError("");
      refresh();
    },
    onError: (reason) => setError(reason instanceof Error ? reason.message : "Could not save shop profile."),
  });
  const signalMutation = useMutation({
    mutationFn: marineSignalsApi.createSignal,
    onSuccess: () => {
      setNewSignal({ ...newSignal, title: "", citation_url: "" });
      setError("");
      refresh();
    },
    onError: (reason) => setError(reason instanceof Error ? reason.message : "Could not add signal."),
  });
  const reviewMutation = useMutation({
    mutationFn: ({ id, values }: { id: string; values: typeof reviewFields }) =>
      marineSignalsApi.review(id, values),
    onSuccess: () => {
      setReviewing(null);
      setError("");
      refresh();
    },
    onError: (reason) => setError(reason instanceof Error ? reason.message : "Could not publish review."),
  });
  const feedbackMutation = useMutation({
    mutationFn: ({ id, feedback }: { id: string; feedback: "saved" | "dismissed" | "flagged" | "useful" | "acted" }) =>
      marineSignalsApi.feedback(id, feedback),
    onSuccess: refresh,
    onError: (reason) => setError(reason instanceof Error ? reason.message : "Could not save feedback."),
  });
  const statusMutation = useMutation({
    mutationFn: (id: string) => marineSignalsApi.setStatus(id, "superseded"),
    onSuccess: refresh,
    onError: (reason) => setError(reason instanceof Error ? reason.message : "Could not update signal status."),
  });

  if (sourcesQuery.isLoading || signalsQuery.isLoading || metricsQuery.isLoading || profileQuery.isLoading) {
    return <Spinner label="Loading Marine Signals…" />;
  }
  if (sourcesQuery.isError || signalsQuery.isError || metricsQuery.isError || profileQuery.isError) {
    return <ErrorBanner message="Marine Signals could not be loaded. Please try again." />;
  }

  const sources = sourcesQuery.data ?? [];
  const signals = signalsQuery.data ?? [];
  const metrics = metricsQuery.data;
  const needsReview = signals.filter((signal) => signal.status === "needs_review");
  const visibleSignals = signals.filter((signal) => signal.status !== "needs_review");

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Marine Signals</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-600">
          Source-linked operational briefs for your shop. Automated feed items stay in review until an
          authorized person checks the source and adds the shop-specific context and action.
        </p>
      </div>
      {error && <ErrorBanner message={error} />}
      <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
        Operational awareness only—not regulatory or safety advice. Verify current details with the
        cited primary source. Feed terms must be reviewed before enabling a source.
      </div>

      {metrics && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatCard label="Sources checked recently" value={`${metrics.fresh_sources}/${metrics.source_count}`} />
          <StatCard label="Sources needing attention" value={metrics.stale_sources} />
          <StatCard label="Awaiting human review" value={metrics.needs_review} />
          <StatCard label="Citation coverage" value={`${metrics.citation_coverage}%`} />
          <StatCard label="Marked useful" value={metrics.useful_feedback} />
          <StatCard label="Actions taken" value={metrics.acted_feedback} />
          <StatCard label="Feedback total" value={metrics.feedback_count} />
        </div>
      )}

      <Card className="p-5">
        <h2 className="text-lg font-semibold text-slate-900">Shop relevance & delivery</h2>
        <p className="mb-4 mt-1 text-sm text-slate-500">
          Choose the area and topics that should shape your brief. Weekly email includes only published
          items from the last seven days; urgent reviewed items are emailed immediately.
        </p>
        <form
          className="grid gap-4 md:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault();
            profileMutation.mutate({
              ...profile,
              specialties: specialtiesText.split(",").map((value) => value.trim()).filter(Boolean),
            });
          }}
        >
          <Field label="Service area">
            <input className={inputClass} value={profile.service_area} onChange={(event) => setProfile({ ...profile, service_area: event.target.value })} placeholder="Sarasota, Bradenton, Venice" />
          </Field>
          <Field label="Specialties (comma-separated)">
            <input className={inputClass} value={specialtiesText} onChange={(event) => setSpecialtiesText(event.target.value)} placeholder="electrical, fiberglass, trailers" />
          </Field>
          <fieldset className="md:col-span-2">
            <legend className="mb-2 text-sm font-medium text-slate-700">Topics of interest (leave all unchecked for every category)</legend>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {categories.map((category) => (
                <label className="flex items-center gap-2 text-sm text-slate-600" key={category.value}>
                  <input
                    type="checkbox"
                    checked={profile.interests.includes(category.value)}
                    onChange={(event) => setProfile({
                      ...profile,
                      interests: event.target.checked
                        ? [...profile.interests, category.value]
                        : profile.interests.filter((value) => value !== category.value),
                    })}
                  />
                  {category.label}
                </label>
              ))}
            </div>
          </fieldset>
          <Field label="Digest / urgent-alert email">
            <input className={inputClass} type="email" value={profile.digest_email ?? ""} onChange={(event) => setProfile({ ...profile, digest_email: event.target.value || null })} placeholder="operations@example.com" />
          </Field>
          <label className="flex items-center gap-2 self-end pb-2 text-sm text-slate-700">
            <input type="checkbox" checked={profile.digest_enabled} onChange={(event) => setProfile({ ...profile, digest_enabled: event.target.checked })} />
            Enable weekly digest and urgent alerts
          </label>
          <div className="md:col-span-2">
            <Button type="submit" disabled={profileMutation.isPending}>Save shop profile</Button>
          </div>
        </form>
      </Card>

      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Curated sources</h2>
            <p className="mt-1 text-sm text-slate-500">
              Feeds refresh every six hours. Only HTTPS feeds on the approved primary-source domains are accepted.
            </p>
          </div>
        </div>
        {sources.length > 0 && (
          <ul className="my-4 divide-y divide-slate-100">
            {sources.map((source) => (
              <li className="flex flex-wrap items-center justify-between gap-3 py-3" key={source.id}>
                <div>
                  <p className="font-medium text-slate-800">{source.name} <Badge tone={source.enabled ? "green" : "slate"}>{source.enabled ? "Enabled" : "Paused"}</Badge></p>
                  <a className="text-sm text-blue-700 underline" href={source.source_url} target="_blank" rel="noreferrer">{source.source_url}</a>
                  <p className="text-xs text-slate-500">Last checked: {localDate(source.last_checked_at)}{source.last_error ? ` · ${source.last_error}` : ""}</p>
                  <a className="text-xs text-slate-500 underline" href={source.terms_url} target="_blank" rel="noreferrer">Terms reviewed {localDate(source.terms_reviewed_at)}</a>
                </div>
                {isAdmin && <Button variant="secondary" onClick={() => toggleSourceMutation.mutate({ id: source.id, enabled: !source.enabled })}>{source.enabled ? "Pause" : "Enable"}</Button>}
              </li>
            ))}
          </ul>
        )}
        {isAdmin ? (
          <form
            className="grid gap-3 border-t border-slate-100 pt-4 md:grid-cols-2"
            onSubmit={(event) => {
              event.preventDefault();
              sourceMutation.mutate({ ...sourceForm, terms_confirmed: true });
            }}
          >
            <Field label="Source name"><input className={inputClass} required minLength={2} value={sourceForm.name} onChange={(event) => setSourceForm({ ...sourceForm, name: event.target.value })} /></Field>
            <Field label="Topic">
              <select className={inputClass} value={sourceForm.category} onChange={(event) => setSourceForm({ ...sourceForm, category: event.target.value as MarineSignalCategory })}>
                {categories.map((category) => <option value={category.value} key={category.value}>{category.label}</option>)}
              </select>
            </Field>
            <Field label="Primary source URL"><input className={inputClass} type="url" required value={sourceForm.source_url} onChange={(event) => setSourceForm({ ...sourceForm, source_url: event.target.value })} /></Field>
            <Field label="RSS / Atom feed URL (same host)"><input className={inputClass} type="url" required value={sourceForm.feed_url} onChange={(event) => setSourceForm({ ...sourceForm, feed_url: event.target.value })} /></Field>
            <Field label="Terms / licensing URL"><input className={inputClass} type="url" required value={sourceForm.terms_url} onChange={(event) => setSourceForm({ ...sourceForm, terms_url: event.target.value })} /></Field>
            <label className="flex items-center gap-2 self-end pb-2 text-sm text-slate-700">
              <input type="checkbox" required checked={sourceForm.terms_confirmed} onChange={(event) => setSourceForm({ ...sourceForm, terms_confirmed: event.target.checked })} />
              I reviewed the terms and have permission to poll this feed
            </label>
            <div className="md:col-span-2"><Button type="submit" disabled={sourceMutation.isPending}>Add source</Button></div>
          </form>
        ) : (
          <p className="text-sm text-slate-500">Owners and admins manage sources and licensing acknowledgments.</p>
        )}
      </Card>

      {isAdmin && (
        <Card className="p-5">
          <h2 className="text-lg font-semibold text-slate-900">Add a sourced item</h2>
          <p className="mb-4 mt-1 text-sm text-slate-500">Manual entries also require review before they appear in briefs.</p>
          <form className="grid gap-3 md:grid-cols-2" onSubmit={(event) => { event.preventDefault(); signalMutation.mutate(newSignal); }}>
            <Field label="Source"><select className={inputClass} required value={newSignal.source_id} onChange={(event) => setNewSignal({ ...newSignal, source_id: event.target.value })}><option value="">Select source</option>{sources.map((source) => <option key={source.id} value={source.id}>{source.name}</option>)}</select></Field>
            <Field label="Topic"><select className={inputClass} value={newSignal.category} onChange={(event) => setNewSignal({ ...newSignal, category: event.target.value as MarineSignalCategory })}>{categories.map((category) => <option key={category.value} value={category.value}>{category.label}</option>)}</select></Field>
            <Field label="Headline"><input className={inputClass} required minLength={3} value={newSignal.title} onChange={(event) => setNewSignal({ ...newSignal, title: event.target.value })} /></Field>
            <Field label="Primary-source citation URL"><input className={inputClass} type="url" required value={newSignal.citation_url} onChange={(event) => setNewSignal({ ...newSignal, citation_url: event.target.value })} /></Field>
            <Field label="Geography (optional)"><input className={inputClass} value={newSignal.geography} onChange={(event) => setNewSignal({ ...newSignal, geography: event.target.value })} /></Field>
            <div className="self-end"><Button type="submit" disabled={signalMutation.isPending || sources.length === 0}>Add for review</Button></div>
          </form>
        </Card>
      )}

      {needsReview.length > 0 && (
        <section className="flex flex-col gap-3">
          <h2 className="text-lg font-semibold text-slate-900">Needs human review</h2>
          {needsReview.map((signal) => (
            <SignalCard
              key={signal.id}
              signal={signal}
              onFeedback={(feedback) => feedbackMutation.mutate({ id: signal.id, feedback })}
              reviewAction={isAdmin ? <Button onClick={() => { setReviewing(signal); setReviewFields({ summary: signal.summary, why_it_matters: signal.why_it_matters, suggested_action: signal.suggested_action, uncertainty: signal.uncertainty, geography: signal.geography, priority: signal.priority }); }}>Review & publish</Button> : undefined}
            />
          ))}
        </section>
      )}

      {reviewing && isAdmin && (
        <Card className="p-5">
          <h2 className="text-lg font-semibold text-slate-900">Review: {reviewing.title}</h2>
          <p className="my-2 text-sm"><a className="text-blue-700 underline" href={reviewing.citation_url} target="_blank" rel="noreferrer">Open primary-source citation</a></p>
          <p className="mb-4 text-sm text-slate-600">{reviewing.source_content || "No feed summary was provided. Read the source and enter a checked summary."}</p>
          <form className="grid gap-3" onSubmit={(event) => { event.preventDefault(); reviewMutation.mutate({ id: reviewing.id, values: reviewFields }); }}>
            <Field label="What changed (verified summary)"><textarea className={inputClass} required rows={3} value={reviewFields.summary} onChange={(event) => setReviewFields({ ...reviewFields, summary: event.target.value })} /></Field>
            <Field label="Why it matters to this shop"><textarea className={inputClass} required rows={2} value={reviewFields.why_it_matters} onChange={(event) => setReviewFields({ ...reviewFields, why_it_matters: event.target.value })} /></Field>
            <Field label="Suggested action"><textarea className={inputClass} required rows={2} value={reviewFields.suggested_action} onChange={(event) => setReviewFields({ ...reviewFields, suggested_action: event.target.value })} /></Field>
            <div className="grid gap-3 md:grid-cols-2">
              <Field label="Geography"><input className={inputClass} value={reviewFields.geography} onChange={(event) => setReviewFields({ ...reviewFields, geography: event.target.value })} /></Field>
              <Field label="Priority"><select className={inputClass} value={reviewFields.priority} onChange={(event) => setReviewFields({ ...reviewFields, priority: event.target.value as "normal" | "urgent" })}><option value="normal">Normal</option><option value="urgent">Urgent alert</option></select></Field>
            </div>
            <Field label="Uncertainty / verification caveat"><textarea className={inputClass} rows={2} value={reviewFields.uncertainty} onChange={(event) => setReviewFields({ ...reviewFields, uncertainty: event.target.value })} /></Field>
            <div className="flex gap-2">
              <Button type="submit" disabled={reviewMutation.isPending}>Publish reviewed item</Button>
              <Button type="button" variant="secondary" onClick={() => setReviewing(null)}>Cancel</Button>
            </div>
          </form>
        </Card>
      )}

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-slate-900">Published brief</h2>
        {visibleSignals.length === 0 ? (
          <Card className="p-6 text-sm text-slate-500">No published items match this shop profile yet. Configure a licensed source or add a sourced item for review.</Card>
        ) : visibleSignals.map((signal) => (
          <SignalCard
            key={signal.id}
            signal={signal}
            onFeedback={(feedback) => feedbackMutation.mutate({ id: signal.id, feedback })}
            reviewAction={isAdmin ? <Button variant="secondary" onClick={() => statusMutation.mutate(signal.id)}>Mark superseded</Button> : undefined}
          />
        ))}
      </section>
    </div>
  );
}

function SignalCard({
  signal,
  onFeedback,
  reviewAction,
}: {
  signal: MarineSignal;
  onFeedback: (feedback: "saved" | "dismissed" | "flagged" | "useful" | "acted") => void;
  reviewAction?: ReactNode;
}) {
  const label = categories.find((item) => item.value === signal.category)?.label ?? signal.category;
  return (
    <Card className={`p-5 ${signal.priority === "urgent" ? "border-red-300" : ""}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="mb-2 flex flex-wrap gap-2">
            <Badge tone={signal.priority === "urgent" ? "red" : "blue"}>{signal.priority === "urgent" ? "Urgent" : label}</Badge>
            {signal.priority === "urgent" && <Badge tone="red">{label}</Badge>}
            {signal.status !== "published" && <Badge tone="amber">{signal.status.replace("_", " ")}</Badge>}
          </div>
          <h3 className="text-lg font-semibold text-slate-900">{signal.title}</h3>
          <p className="mt-1 text-xs text-slate-500">{signal.source_name} · {signal.geography || "Geography not specified"} · Published {localDate(signal.published_at)}</p>
        </div>
        {reviewAction}
      </div>
      {signal.source_content && <p className="mt-3 whitespace-pre-line text-sm text-slate-600">{signal.source_content}</p>}
      {signal.summary && <p className="mt-3 text-sm text-slate-800"><strong>What changed:</strong> {signal.summary}</p>}
      {signal.why_it_matters && <p className="mt-2 text-sm text-slate-800"><strong>Why it matters:</strong> {signal.why_it_matters}</p>}
      {signal.suggested_action && <p className="mt-2 text-sm text-slate-800"><strong>Suggested action:</strong> {signal.suggested_action}</p>}
      <p className="mt-2 text-sm text-amber-800"><strong>Uncertainty:</strong> {signal.uncertainty || "Verify current conditions and details at the primary source."}</p>
      <a className="mt-3 inline-block text-sm text-blue-700 underline" href={signal.citation_url} target="_blank" rel="noreferrer">View primary source ↗</a>
      <p className="mt-1 text-xs text-slate-400">Last checked {localDate(signal.last_checked_at)}{signal.effective_until ? ` · Effective through ${localDate(signal.effective_until)}` : ""}</p>
      {signal.status === "published" && (
        <div className="mt-4 flex flex-wrap gap-2 border-t border-slate-100 pt-3">
          {(["saved", "useful", "acted", "flagged", "dismissed"] as const).map((feedback) => (
            <Button key={feedback} variant={signal.feedback === feedback ? "primary" : "secondary"} onClick={() => onFeedback(feedback)}>
              {feedback === "acted" ? "Action taken" : feedback[0]!.toUpperCase() + feedback.slice(1)}
            </Button>
          ))}
        </div>
      )}
    </Card>
  );
}
