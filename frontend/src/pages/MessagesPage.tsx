import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { messagesApi } from "../lib/services";
import { ApiError } from "../lib/api";
import { Badge, Button, Card, EmptyState, ErrorBanner, Spinner, inputClass } from "../components/ui";
import type { InboxMessage } from "../types/api";

function formatDate(value: string): string {
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** Staff-side "Messages" panel — the office view of the customer portal's
 * messaging thread (see `app/api/v1/routes/messages.py`). Company-wide
 * inbox, newest first, with an unread filter and a reply box per thread. */
export function MessagesPage() {
  const queryClient = useQueryClient();
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [activeCustomerId, setActiveCustomerId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [sendError, setSendError] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ["messages", "inbox", unreadOnly],
    queryFn: () => messagesApi.inbox(unreadOnly),
  });

  const markReadMutation = useMutation({
    mutationFn: (id: string) => messagesApi.markRead(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["messages", "inbox"] }),
  });

  const replyMutation = useMutation({
    mutationFn: () =>
      messagesApi.reply({ customer_id: activeCustomerId!, body: draft }),
    onSuccess: () => {
      setDraft("");
      queryClient.invalidateQueries({ queryKey: ["messages", "inbox"] });
    },
    onError: (err) =>
      setSendError(err instanceof ApiError ? err.message : "Failed to send reply."),
  });

  function handleReply(e: FormEvent) {
    e.preventDefault();
    setSendError(null);
    if (!draft.trim() || !activeCustomerId) return;
    replyMutation.mutate();
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Messages</h1>
          <p className="mt-1 text-sm text-slate-500">
            Customer conversations from the self-service portal.
          </p>
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-600">
          <input
            type="checkbox"
            checked={unreadOnly}
            onChange={(e) => setUnreadOnly(e.target.checked)}
          />
          Unread only
        </label>
      </div>

      {query.isLoading && <Spinner label="Loading messages…" />}
      {query.isError && (
        <ErrorBanner
          message={query.error instanceof Error ? query.error.message : "Failed to load messages."}
        />
      )}
      {query.isSuccess && query.data.length === 0 && (
        <EmptyState message="No messages yet." />
      )}

      {query.isSuccess && query.data.length > 0 && (
        <Card>
          <ul className="divide-y divide-slate-100">
            {query.data.map((m: InboxMessage) => (
              <li key={m.id} className="flex flex-col gap-2 px-4 py-3 text-sm">
                <div className="flex items-center justify-between">
                  <div>
                    <span className="font-medium text-slate-900">
                      {m.customer_label ?? "Unknown customer"}
                    </span>
                    <span className="ml-2 text-xs uppercase tracking-wide text-slate-400">
                      {m.sender_type === "customer" ? "From customer" : "From staff"}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    {!m.read_at && m.sender_type === "customer" && (
                      <Badge tone="amber">Unread</Badge>
                    )}
                    <span className="text-xs text-slate-400">{formatDate(m.created_at)}</span>
                  </div>
                </div>
                <p className="text-slate-700">{m.body}</p>
                <div className="flex gap-2">
                  {!m.read_at && m.sender_type === "customer" && (
                    <Button
                      variant="secondary"
                      onClick={() => markReadMutation.mutate(m.id)}
                      disabled={markReadMutation.isPending}
                    >
                      Mark read
                    </Button>
                  )}
                  <Button variant="secondary" onClick={() => setActiveCustomerId(m.customer_id)}>
                    Reply
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {activeCustomerId && (
        <Card className="p-4">
          <h2 className="mb-2 text-sm font-semibold text-slate-900">Reply to customer</h2>
          <form onSubmit={handleReply} className="flex flex-col gap-2">
            {sendError && <ErrorBanner message={sendError} />}
            <textarea
              className={`${inputClass} min-h-[80px]`}
              placeholder="Type your reply…"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              aria-label="Reply"
            />
            <div className="flex gap-2">
              <Button type="submit" disabled={replyMutation.isPending || !draft.trim()}>
                {replyMutation.isPending ? "Sending…" : "Send reply"}
              </Button>
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setActiveCustomerId(null);
                  setDraft("");
                }}
              >
                Cancel
              </Button>
            </div>
          </form>
        </Card>
      )}
    </div>
  );
}
