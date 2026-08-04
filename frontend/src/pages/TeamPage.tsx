import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { authApi, usersApi } from "../lib/services";
import { ApiError } from "../lib/api";
import { canManageUsers, useAuth } from "../context/AuthContext";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Field,
  Spinner,
  inputClass,
} from "../components/ui";
import type { InviteOut, TeamMember, UserRole, UserUpdateInput } from "../types/api";

// Phase 10: this used to be invite-only because the backend had no
// "list users" endpoint (see git history for the prior version of this
// file). GET /users + PATCH /users/{id} now exist (app/api/v1/routes/
// users.py), so this page shows the full roster and supports editing —
// your own profile (any authenticated role) or, for owners/admins, any
// teammate's role/active-status/skills/name/address too.
export function TeamPage() {
  const { user: currentUser } = useAuth();
  const isAdmin = canManageUsers(currentUser?.role);
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<TeamMember | null>(null);
  const [showInvite, setShowInvite] = useState(false);

  const rosterQuery = useQuery({
    queryKey: ["users"],
    queryFn: () => usersApi.list(),
  });

  function afterSave() {
    queryClient.invalidateQueries({ queryKey: ["users"] });
    setEditing(null);
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Team</h1>
          <p className="mt-1 text-sm text-slate-500">
            Everyone in your company, their skills, and whether their home address is
            geocoded for distance-aware dispatch.
          </p>
        </div>
        {isAdmin && (
          <Button onClick={() => setShowInvite(true)}>Invite teammate</Button>
        )}
      </div>

      {rosterQuery.isLoading && <Spinner label="Loading team…" />}
      {rosterQuery.isError && (
        <ErrorBanner
          message={
            rosterQuery.error instanceof ApiError
              ? rosterQuery.error.message
              : "Failed to load team roster."
          }
        />
      )}
      {rosterQuery.data && rosterQuery.data.length === 0 && (
        <EmptyState message="No teammates yet." />
      )}

      {rosterQuery.data && rosterQuery.data.length > 0 && (
        <Card className="overflow-hidden">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Email</th>
                <th className="px-4 py-3">Role</th>
                <th className="px-4 py-3">Skills</th>
                <th className="px-4 py-3">Home address</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rosterQuery.data.map((member) => {
                const isSelf = member.id === currentUser?.id;
                const canEdit = isAdmin || isSelf;
                const geocoded = member.home_latitude !== null && member.home_longitude !== null;
                return (
                  <tr key={member.id} className={isSelf ? "bg-slate-50/60" : undefined}>
                    <td className="px-4 py-3 font-medium text-slate-900">
                      {member.full_name ?? "—"}
                      {isSelf && <span className="ml-2 text-xs font-normal text-slate-400">(you)</span>}
                    </td>
                    <td className="px-4 py-3 text-slate-600">{member.email}</td>
                    <td className="px-4 py-3">
                      <Badge tone={member.role === "owner" || member.role === "admin" ? "blue" : "slate"}>
                        {member.role}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-slate-600">
                      {member.skills.length > 0 ? member.skills.join(", ") : "—"}
                    </td>
                    <td className="px-4 py-3 text-slate-600">
                      {member.address_text ? (
                        <span className="flex items-center gap-1.5">
                          <span className="max-w-[16rem] truncate">{member.address_text}</span>
                          <Badge tone={geocoded ? "green" : "amber"}>
                            {geocoded ? "located" : "not located"}
                          </Badge>
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <Badge tone={member.is_active ? "green" : "red"}>
                        {member.is_active ? "Active" : "Inactive"}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-right">
                      {canEdit && (
                        <Button variant="secondary" onClick={() => setEditing(member)}>
                          Edit
                        </Button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}

      {editing && (
        <EditProfileModal
          member={editing}
          isAdmin={isAdmin}
          isSelf={editing.id === currentUser?.id}
          onClose={() => setEditing(null)}
          onSaved={afterSave}
        />
      )}

      {showInvite && <InviteModal onClose={() => setShowInvite(false)} />}
    </div>
  );
}

function EditProfileModal({
  member,
  isAdmin,
  isSelf,
  onClose,
  onSaved,
}: {
  member: TeamMember;
  isAdmin: boolean;
  isSelf: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [fullName, setFullName] = useState(member.full_name ?? "");
  const [skillsText, setSkillsText] = useState(member.skills.join(", "));
  const [addressText, setAddressText] = useState(member.address_text ?? "");
  const [role, setRole] = useState<UserRole>(member.role);
  const [isActive, setIsActive] = useState(member.is_active);
  const [error, setError] = useState<string | null>(null);

  // Admins editing someone else may also change role/is_active; nobody
  // (including admins editing their OWN row here) can lock themselves out
  // by accident through this form — the backend enforces the real rule
  // (an admin CAN edit their own role/is_active via the admin path), this
  // UI simply doesn't surface those two controls for a self-edit to avoid
  // an easy foot-gun of an admin demoting themselves by mistake.
  const canEditRestricted = isAdmin && !isSelf;

  const mutation = useMutation({
    mutationFn: () => {
      const body: UserUpdateInput = {
        full_name: fullName || null,
        skills: skillsText
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        address_text: addressText || null,
      };
      if (canEditRestricted) {
        body.role = role;
        body.is_active = isActive;
      }
      return usersApi.update(member.id, body);
    },
    onSuccess: onSaved,
    onError: (err) => setError(err instanceof ApiError ? err.message : "Failed to save profile."),
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    mutation.mutate();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-lg bg-white p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-900">
            Edit {isSelf ? "your profile" : member.full_name ?? member.email}
          </h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          >
            ✕
          </button>
        </div>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          {error && <ErrorBanner message={error} />}
          <Field label="Full name">
            <input className={inputClass} value={fullName} onChange={(e) => setFullName(e.target.value)} />
          </Field>
          <Field label="Skills (comma-separated)">
            <input
              className={inputClass}
              placeholder="outboard, electrical, fiberglass"
              value={skillsText}
              onChange={(e) => setSkillsText(e.target.value)}
            />
          </Field>
          <Field label="Home address">
            <input
              className={inputClass}
              placeholder="123 Main St, Sarasota, FL 34234"
              value={addressText}
              onChange={(e) => setAddressText(e.target.value)}
            />
          </Field>
          <p className="-mt-2 text-xs text-slate-400">
            Used only to estimate distance for the dispatch engine. Geocoded automatically
            on save (OpenStreetMap Nominatim) — if it can't be located, everything else you
            change here still saves.
          </p>
          {canEditRestricted && (
            <>
              <Field label="Role">
                <select className={inputClass} value={role} onChange={(e) => setRole(e.target.value as UserRole)}>
                  <option value="technician">Technician</option>
                  <option value="office">Office</option>
                  <option value="admin">Admin</option>
                  <option value="owner">Owner</option>
                </select>
              </Field>
              <label className="flex items-center gap-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={isActive}
                  onChange={(e) => setIsActive(e.target.checked)}
                />
                Active
              </label>
            </>
          )}
          <div className="mt-2 flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? "Saving…" : "Save"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

function InviteModal({ onClose }: { onClose: () => void }) {
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState<UserRole>("technician");
  const [error, setError] = useState<string | null>(null);
  const [invite, setInvite] = useState<InviteOut | null>(null);
  const [copied, setCopied] = useState(false);
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: () => authApi.createInvite({ email, role, full_name: fullName || undefined }),
    onSuccess: (result) => {
      setError(null);
      setInvite(result);
      setCopied(false);
      setEmail("");
      setFullName("");
      queryClient.invalidateQueries({ queryKey: ["users"] });
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-lg bg-white p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-900">Invite a teammate</h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          >
            ✕
          </button>
        </div>
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
          <div className="mt-2 flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={onClose}>
              Close
            </Button>
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? "Sending invite…" : "Send invite"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
