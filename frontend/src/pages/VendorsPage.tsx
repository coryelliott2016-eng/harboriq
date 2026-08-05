import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { vendorsApi } from "../lib/services";
import { ApiError } from "../lib/api";
import { canManageOperations, useAuth } from "../context/AuthContext";
import {
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Field,
  Modal,
  Spinner,
  inputClass,
} from "../components/ui";
import type { Vendor, VendorInput } from "../types/api";

// Phase 13: parts suppliers. Plain CRUD, no delete -- a vendor referenced by
// a purchase order or as an item's default_vendor_id must stay resolvable.
export function VendorsPage() {
  const { user } = useAuth();
  const canWrite = canManageOperations(user?.role);
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<Vendor | null>(null);
  const [includeInactive, setIncludeInactive] = useState(false);

  const vendorsQuery = useQuery({
    queryKey: ["vendors", { search, includeInactive }],
    queryFn: () => vendorsApi.list(search || undefined, includeInactive),
  });

  const statusMutation = useMutation({
    mutationFn: ({ id, isActive }: { id: string; isActive: boolean }) =>
      vendorsApi.setStatus(id, isActive),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["vendors"] }),
  });

  function afterSave() {
    queryClient.invalidateQueries({ queryKey: ["vendors"] });
    setShowCreate(false);
    setEditing(null);
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Vendors</h1>
          <p className="mt-1 text-sm text-slate-500">Parts suppliers you place purchase orders with.</p>
        </div>
        {canWrite && <Button onClick={() => setShowCreate(true)}>New vendor</Button>}
      </div>

      <div className="flex flex-wrap items-center gap-4">
        <input
          className={inputClass}
          placeholder="Search vendors"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <label className="flex items-center gap-2 text-sm text-slate-600">
          <input
            type="checkbox"
            checked={includeInactive}
            onChange={(e) => setIncludeInactive(e.target.checked)}
          />
          Show archived vendors
        </label>
      </div>

      {vendorsQuery.isLoading && <Spinner label="Loading vendors…" />}
      {vendorsQuery.isError && (
        <ErrorBanner
          message={
            vendorsQuery.error instanceof ApiError
              ? vendorsQuery.error.message
              : "Failed to load vendors."
          }
        />
      )}
      {vendorsQuery.data && vendorsQuery.data.length === 0 && (
        <EmptyState message="No vendors yet." />
      )}

      {vendorsQuery.data && vendorsQuery.data.length > 0 && (
        <Card className="overflow-hidden">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Email</th>
                <th className="px-4 py-3">Phone</th>
                <th className="px-4 py-3">Notes</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {vendorsQuery.data.map((vendor) => (
                <tr key={vendor.id} className={vendor.is_active ? undefined : "opacity-60"}>
                  <td className="px-4 py-3 font-medium text-slate-900">{vendor.name}</td>
                  <td className="px-4 py-3 text-slate-600">{vendor.contact_email ?? "—"}</td>
                  <td className="px-4 py-3 text-slate-600">{vendor.contact_phone ?? "—"}</td>
                  <td className="px-4 py-3 max-w-xs truncate text-slate-600">{vendor.notes ?? "—"}</td>
                  <td className="px-4 py-3 text-slate-600">
                    {vendor.is_active ? "Active" : "Archived"}
                  </td>
                  <td className="px-4 py-3 text-right space-x-2">
                    {canWrite && (
                      <Button variant="secondary" onClick={() => setEditing(vendor)}>
                        Edit
                      </Button>
                    )}
                    {canWrite && (
                      <Button
                        variant="secondary"
                        disabled={statusMutation.isPending}
                        onClick={() =>
                          statusMutation.mutate({ id: vendor.id, isActive: !vendor.is_active })
                        }
                      >
                        {vendor.is_active ? "Archive" : "Reactivate"}
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {showCreate && <VendorModal onClose={() => setShowCreate(false)} onSaved={afterSave} />}
      {editing && (
        <VendorModal vendor={editing} onClose={() => setEditing(null)} onSaved={afterSave} />
      )}
    </div>
  );
}

function VendorModal({
  vendor,
  onClose,
  onSaved,
}: {
  vendor?: Vendor;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(vendor?.name ?? "");
  const [contactEmail, setContactEmail] = useState(vendor?.contact_email ?? "");
  const [contactPhone, setContactPhone] = useState(vendor?.contact_phone ?? "");
  const [notes, setNotes] = useState(vendor?.notes ?? "");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => {
      const body: VendorInput = {
        name,
        contact_email: contactEmail || null,
        contact_phone: contactPhone || null,
        notes: notes || null,
      };
      return vendor ? vendorsApi.update(vendor.id, body) : vendorsApi.create(body);
    },
    onSuccess: onSaved,
    onError: (err) => setError(err instanceof ApiError ? err.message : "Failed to save vendor."),
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    mutation.mutate();
  }

  return (
    <Modal title={vendor ? `Edit ${vendor.name}` : "New vendor"} onClose={onClose}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        {error && <ErrorBanner message={error} />}
        <Field label="Name">
          <input
            required
            className={inputClass}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        <Field label="Contact email (optional)">
          <input
            type="email"
            className={inputClass}
            value={contactEmail ?? ""}
            onChange={(e) => setContactEmail(e.target.value)}
          />
        </Field>
        <Field label="Contact phone (optional)">
          <input
            className={inputClass}
            value={contactPhone ?? ""}
            onChange={(e) => setContactPhone(e.target.value)}
          />
        </Field>
        <Field label="Notes (optional)">
          <textarea
            className={inputClass}
            rows={3}
            value={notes ?? ""}
            onChange={(e) => setNotes(e.target.value)}
          />
        </Field>
        <div className="mt-2 flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? "Saving…" : "Save"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
