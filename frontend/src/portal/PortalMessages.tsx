import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { portalApi } from "../lib/services";
import { ApiError } from "../lib/api";
import { Button, Card, EmptyState, ErrorBanner, Spinner, inputClass } from "../components/ui";
import { PortalLayout, PORTAL_INVALID_LINK_MESSAGE } from "./PortalLayout";

function formatDate(value: string): string {
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function PortalMessages() {
  const { token } = useParams<{ token: string }>();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState("");
  const [sendError, setSendError] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ["portal", token, "messages"],
    queryFn: () => portalApi.messages(token!),
    enabled: !!token,
    retry: false,
  });

  const sendMutation = useMutation({
    mutationFn: () => portalApi.sendMessage(token!, { body: draft }),
    onSuccess: () => {
      setDraft("");
      queryClient.invalidateQueries({ queryKey: ["portal", token, "messages"] });
    },
    onError: () => setSendError("Could not send your message. Please try again."),
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSendError(null);
    if (!draft.trim()) return;
    sendMutation.mutate();
  }

  return (
    <PortalLayout>
      <h2 className="mb-4 text-lg font-semibold text-slate-900">Messages</h2>

      {query.isLoading && <Spinner label="Loading your messages…" />}

      {query.isError && (
        <ErrorBanner
          message={
            query.error instanceof ApiError && query.error.status === 404
              ? PORTAL_INVALID_LINK_MESSAGE
              : "Something went wrong loading your messages. Please contact the shop."
          }
        />
      )}

      {query.isSuccess && (
        <div className="flex flex-col gap-4">
          {query.data.length === 0 && <EmptyState message="No messages yet — send one below." />}
          {query.data.length > 0 && (
            <Card className="flex flex-col gap-3 p-4">
              {query.data.map((m) => (
                <div
                  key={m.id}
                  className={`max-w-[80%] rounded-md px-3 py-2 text-sm ${
                    m.sender_type === "customer"
                      ? "ml-auto bg-slate-900 text-white"
                      : "bg-slate-100 text-slate-900"
                  }`}
                >
                  <p>{m.body}</p>
                  <p
                    className={`mt-1 text-xs ${
                      m.sender_type === "customer" ? "text-slate-300" : "text-slate-500"
                    }`}
                  >
                    {m.sender_type === "customer" ? "You" : "Shop"} · {formatDate(m.created_at)}
                  </p>
                </div>
              ))}
            </Card>
          )}

          <form onSubmit={handleSubmit} className="flex flex-col gap-2">
            {sendError && <ErrorBanner message={sendError} />}
            <textarea
              className={`${inputClass} min-h-[80px]`}
              placeholder="Type a message to the shop…"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              aria-label="Message"
            />
            <div>
              <Button type="submit" disabled={sendMutation.isPending || !draft.trim()}>
                {sendMutation.isPending ? "Sending…" : "Send"}
              </Button>
            </div>
          </form>
        </div>
      )}
    </PortalLayout>
  );
}
