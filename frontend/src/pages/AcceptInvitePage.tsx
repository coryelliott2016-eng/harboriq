import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { authApi } from "../lib/services";
import { ApiError } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { Button, Card, ErrorBanner, Field, Spinner, inputClass } from "../components/ui";

// Public (unauthenticated) route, mirroring PublicInvoicePage's structure: it
// lives outside the authenticated app shell entirely (see App.tsx), fetches
// its own data by token, and renders its own full-page layout rather than
// nesting inside <AppShell>.
export function AcceptInvitePage() {
  const { token } = useParams<{ token: string }>();
  const { user, acceptInvite } = useAuth();
  const navigate = useNavigate();

  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const preview = useQuery({
    queryKey: ["invite-preview", token],
    queryFn: () => authApi.getInvite(token!),
    enabled: !!token,
    retry: false,
  });

  const mutation = useMutation({
    mutationFn: () => acceptInvite(token!, { password, full_name: fullName || undefined }),
    onSuccess: () => navigate("/", { replace: true }),
    onError: (err) => setError(err instanceof ApiError ? err.message : "Unable to accept this invite."),
  });

  // Already-logged-in users (e.g. an admin who clicked their own invite link
  // to test it) shouldn't get stuck here — send them to the app.
  if (user) return <Navigate to="/" replace />;

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    mutation.mutate();
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-sm">
        <h1 className="mb-6 text-center text-xl font-semibold text-slate-900">HarborIQ</h1>

        {preview.isLoading && <Spinner label="Loading your invite…" />}

        {preview.isError && (
          <Card className="p-6">
            <ErrorBanner
              message={
                preview.error instanceof ApiError && preview.error.status === 404
                  ? "This invite link is invalid, expired, or has already been used."
                  : "Something went wrong loading this invite. Please contact the person who invited you."
              }
            />
          </Card>
        )}

        {preview.isSuccess && (
          <Card className="p-8">
            <p className="text-sm text-slate-500">
              You've been invited to join <strong>{preview.data.company_name}</strong> as{" "}
              {preview.data.role}.
            </p>
            <p className="mt-1 text-sm text-slate-500">
              Set a password for <strong>{preview.data.email}</strong> to finish creating your
              account.
            </p>

            <form onSubmit={handleSubmit} className="mt-6 flex flex-col gap-4">
              {error && <ErrorBanner message={error} />}
              <Field label="Your name (optional)">
                <input
                  className={inputClass}
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder={preview.data.full_name ?? undefined}
                />
              </Field>
              <Field label="Password">
                <input
                  type="password"
                  required
                  minLength={12}
                  className={inputClass}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="new-password"
                />
              </Field>
              <p className="text-xs text-slate-400">At least 12 characters.</p>
              <Button type="submit" disabled={mutation.isPending} className="mt-2 w-full">
                {mutation.isPending ? "Creating account…" : "Accept invite & log in"}
              </Button>
            </form>
          </Card>
        )}
      </div>
    </div>
  );
}
