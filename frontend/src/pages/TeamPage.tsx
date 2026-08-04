import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { authApi } from "../lib/services";
import { ApiError } from "../lib/api";
import { Button, Card, ErrorBanner, Field, inputClass } from "../components/ui";
import type { InviteOut, UserRole } from "../types/api";

// NOTE: the backend has no GET-all-users endpoint (checked app/api/v1/routes/auth.py
// — only POST /auth/invites, GET /auth/invites/{token}, POST /auth/invites/{token}/accept,
// GET /auth/me exist). This screen is deliberately "invite only": it does not fabricate
// a member list from thin air. A real team roster needs a backend list-users endpoint —
// flagged as a backend gap in the README, not worked around here.
//
// Phase 5 change: teammates are now provisioned via a one-time invite link (see
// app/services/auth.py::create_invite/accept_invite) rather than an admin picking a
// temporary password on the invitee's behalf. The invitee sets their own password when
// they open the link, which is both a better security posture (no shared secret ever
// exists) and a better first-run experience.
export function TeamPage() {
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState<UserRole>("technician");
  const [error, setError] = useState<string | null>(null);
  const [invite, setInvite] = useState<InviteOut | null>(null);
  const [copied, setCopied] = useState(false);

  const mutation = useMutation({
    mutationFn: () => authApi.createInvite({ email, role, full_name: fullName || undefined }),
    onSuccess: (result) => {
      setError(null);
      setInvite(result);
      setCopied(false);
      setEmail("");
      setFullName("");
    },
    onError: (err) => {
      setInvite(null);
      setError(err instanceof ApiError ? err.message : "Failed to invite teammate.");
    },
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    mutation.mutate();
  }

  async function copyAcceptUrl() {
    if (!invite) return;
    await navigator.clipboard.writeText(invite.accept_url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Team</h1>
        <p className="mt-1 text-sm text-slate-500">Invite a teammate to your company.</p>
      </div>

      <Card className="max-w-md p-5">
        <p className="mb-4 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800">
          There is currently no way to list existing teammates — the backend does not
          yet expose a "list users" endpoint. This is invite-only for now; see the
          README for details.
        </p>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          {error && <ErrorBanner message={error} />}
          {invite && (
            <div className="rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">
              <p>
                Invited <strong>{invite.email}</strong> as {invite.role}. Share this link
                with them — it expires in {invite.expires_in_hours} hours and can only be
                used once.
              </p>
              <div className="mt-3 flex items-center gap-2 rounded-md border border-green-200 bg-white px-3 py-2">
                <p className="flex-1 break-all text-xs text-slate-900">{invite.accept_url}</p>
                <Button type="button" variant="secondary" onClick={() => void copyAcceptUrl()}>
                  {copied ? "Copied!" : "Copy link"}
                </Button>
              </div>
            </div>
          )}
          <Field label="Email">
            <input
              type="email"
              required
              className={inputClass}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </Field>
          <Field label="Full name (optional)">
            <input className={inputClass} value={fullName} onChange={(e) => setFullName(e.target.value)} />
          </Field>
          <Field label="Role">
            <select className={inputClass} value={role} onChange={(e) => setRole(e.target.value as UserRole)}>
              <option value="technician">Technician</option>
              <option value="office">Office</option>
              <option value="admin">Admin</option>
              <option value="owner">Owner</option>
            </select>
          </Field>
          <Button type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? "Sending invite…" : "Send invite"}
          </Button>
        </form>
      </Card>
    </div>
  );
}
