import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { authApi } from "../lib/services";
import { ApiError } from "../lib/api";
import { Button, Card, ErrorBanner, Field, inputClass } from "../components/ui";
import type { UserRole } from "../types/api";

// NOTE: the backend has no GET-all-users endpoint (checked app/api/v1/routes/auth.py
// — only POST /auth/users, GET /auth/me exist). This screen is deliberately
// "invite only": it does not fabricate a member list from thin air. A real
// team roster needs a backend list-users endpoint — flagged as a backend gap
// in the Phase 4 report / README, not worked around here.
export function TeamPage() {
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<UserRole>("technician");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => authApi.createUser({ email, password, role, full_name: fullName || undefined }),
    onSuccess: (user) => {
      setError(null);
      setSuccess(`Invited ${user.email} as ${user.role}.`);
      setEmail("");
      setFullName("");
      setPassword("");
    },
    onError: (err) => {
      setSuccess(null);
      setError(err instanceof ApiError ? err.message : "Failed to invite teammate.");
    },
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    mutation.mutate();
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
          {success && (
            <div className="rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">
              {success}
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
          <Field label="Temporary password">
            <input
              type="password"
              required
              minLength={12}
              className={inputClass}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
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
            {mutation.isPending ? "Inviting…" : "Invite teammate"}
          </Button>
        </form>
      </Card>
    </div>
  );
}
