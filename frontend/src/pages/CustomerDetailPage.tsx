import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { customersApi, vesselsApi } from "../lib/services";
import { ApiError } from "../lib/api";
import { useAuth, canManageOperations } from "../context/AuthContext";
import {
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Field,
  Modal,
  Spinner,
  customerName,
  inputClass,
} from "../components/ui";
import type { VesselInput } from "../types/api";

export function CustomerDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const canWrite = canManageOperations(user?.role);
  const [showNewVessel, setShowNewVessel] = useState(false);

  const customerQuery = useQuery({
    queryKey: ["customers", id],
    queryFn: () => customersApi.get(id!),
    enabled: !!id,
  });
  const vesselsQuery = useQuery({
    queryKey: ["customers", id, "vessels"],
    queryFn: () => customersApi.vessels(id!),
    enabled: !!id,
  });

  if (!id) return <ErrorBanner message="Missing customer id." />;
  if (customerQuery.isLoading) return <Spinner label="Loading customer…" />;
  if (customerQuery.isError)
    return (
      <ErrorBanner
        message={customerQuery.error instanceof Error ? customerQuery.error.message : "Failed to load customer."}
      />
    );

  const customer = customerQuery.data!;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link to="/customers" className="text-sm text-slate-500 hover:underline">
          ← All customers
        </Link>
        <h1 className="mt-1 text-2xl font-semibold text-slate-900">{customerName(customer)}</h1>
      </div>

      <Card className="grid grid-cols-2 gap-4 p-5 text-sm sm:grid-cols-3">
        <div>
          <p className="text-xs uppercase text-slate-400">Email</p>
          <p className="text-slate-900">{customer.email ?? "—"}</p>
        </div>
        <div>
          <p className="text-xs uppercase text-slate-400">Phone</p>
          <p className="text-slate-900">{customer.phone ?? "—"}</p>
        </div>
        <div>
          <p className="text-xs uppercase text-slate-400">Address</p>
          <p className="text-slate-900">
            {[customer.address_line1, customer.city, customer.state].filter(Boolean).join(", ") || "—"}
          </p>
        </div>
      </Card>

      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-900">Vessels</h2>
        {canWrite && <Button onClick={() => setShowNewVessel(true)}>New vessel</Button>}
      </div>

      {vesselsQuery.isLoading && <Spinner label="Loading vessels…" />}
      {vesselsQuery.isError && (
        <ErrorBanner
          message={vesselsQuery.error instanceof Error ? vesselsQuery.error.message : "Failed to load vessels."}
        />
      )}
      {vesselsQuery.isSuccess && vesselsQuery.data.length === 0 && (
        <EmptyState message="No vessels on file for this customer yet." />
      )}
      {vesselsQuery.isSuccess && vesselsQuery.data.length > 0 && (
        <Card>
          <ul className="divide-y divide-slate-100">
            {vesselsQuery.data.map((v) => (
              <li key={v.id} className="flex items-center justify-between px-4 py-3 text-sm">
                <span className="font-medium text-slate-900">
                  {v.name ?? (`${v.make ?? ""} ${v.model ?? ""}`.trim() || "Unnamed vessel")}
                </span>
                <span className="text-slate-500">
                  {[v.make, v.model, v.year].filter(Boolean).join(" ") || "—"}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {showNewVessel && (
        <NewVesselModal customerId={id} onClose={() => setShowNewVessel(false)} />
      )}
    </div>
  );
}

function NewVesselModal({ customerId, onClose }: { customerId: string; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<Omit<VesselInput, "customer_id">>({ name: "", make: "", model: "", year: null });
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => vesselsApi.create({ ...form, customer_id: customerId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["customers", customerId, "vessels"] });
      onClose();
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : "Failed to create vessel."),
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    mutation.mutate();
  }

  return (
    <Modal title="New vessel" onClose={onClose}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        {error && <ErrorBanner message={error} />}
        <Field label="Name">
          <input
            className={inputClass}
            value={form.name ?? ""}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Make">
            <input
              className={inputClass}
              value={form.make ?? ""}
              onChange={(e) => setForm({ ...form, make: e.target.value })}
            />
          </Field>
          <Field label="Model">
            <input
              className={inputClass}
              value={form.model ?? ""}
              onChange={(e) => setForm({ ...form, model: e.target.value })}
            />
          </Field>
        </div>
        <Field label="Year">
          <input
            type="number"
            className={inputClass}
            value={form.year ?? ""}
            onChange={(e) => setForm({ ...form, year: e.target.value ? Number(e.target.value) : null })}
          />
        </Field>
        <div className="mt-2 flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? "Saving…" : "Create vessel"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
