import { useMemo, useState } from "react";
import { canManageOperations, useAuth } from "../context/auth";
import { customerName } from "../lib/format";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { customersApi } from "../lib/services";
import { ApiError } from "../lib/api";
import { Button, Card, EmptyState, ErrorBanner, Field, Modal, Spinner, inputClass } from "../components/ui";
import type { CustomerInput } from "../types/api";

const emptyForm: CustomerInput = {
  first_name: "",
  last_name: "",
  company_name: "",
  email: "",
  phone: "",
};

export function CustomersPage() {
  const { user } = useAuth();
  const canWrite = canManageOperations(user?.role);
  const [search, setSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);

  const query = useQuery({ queryKey: ["customers"], queryFn: () => customersApi.list() });

  const filtered = useMemo(() => {
    const list = query.data ?? [];
    if (!search.trim()) return list;
    const term = search.toLowerCase();
    return list.filter((c) =>
      [customerName(c), c.email, c.phone].filter(Boolean).some((v) => v!.toLowerCase().includes(term)),
    );
  }, [query.data, search]);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Customers</h1>
          <p className="mt-1 text-sm text-slate-500">The shop's customer book.</p>
        </div>
        {canWrite && <Button onClick={() => setShowCreate(true)}>New customer</Button>}
      </div>

      <input
        placeholder="Search by name, email or phone…"
        className={`${inputClass} max-w-sm`}
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />

      {query.isLoading && <Spinner label="Loading customers…" />}
      {query.isError && (
        <ErrorBanner message={query.error instanceof Error ? query.error.message : "Failed to load customers."} />
      )}

      {query.isSuccess && filtered.length === 0 && (
        <EmptyState message={search ? "No customers match your search." : "No customers yet."} />
      )}

      {query.isSuccess && filtered.length > 0 && (
        <Card>
          <ul className="divide-y divide-slate-100">
            {filtered.map((c) => (
              <li key={c.id} className="flex items-center justify-between px-4 py-3">
                <Link to={`/customers/${c.id}`} className="text-sm font-medium text-slate-900 hover:underline">
                  {customerName(c)}
                </Link>
                <span className="text-sm text-slate-500">{c.email ?? c.phone ?? "—"}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {showCreate && <CreateCustomerModal onClose={() => setShowCreate(false)} />}
    </div>
  );
}

function CreateCustomerModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<CustomerInput>(emptyForm);
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => customersApi.create(form),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["customers"] });
      onClose();
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : "Failed to create customer."),
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    mutation.mutate();
  }

  return (
    <Modal title="New customer" onClose={onClose}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        {error && <ErrorBanner message={error} />}
        <div className="grid grid-cols-2 gap-4">
          <Field label="First name">
            <input
              className={inputClass}
              value={form.first_name ?? ""}
              onChange={(e) => setForm({ ...form, first_name: e.target.value })}
            />
          </Field>
          <Field label="Last name">
            <input
              className={inputClass}
              value={form.last_name ?? ""}
              onChange={(e) => setForm({ ...form, last_name: e.target.value })}
            />
          </Field>
        </div>
        <Field label="Company name (optional)">
          <input
            className={inputClass}
            value={form.company_name ?? ""}
            onChange={(e) => setForm({ ...form, company_name: e.target.value })}
          />
        </Field>
        <Field label="Email">
          <input
            type="email"
            className={inputClass}
            value={form.email ?? ""}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
          />
        </Field>
        <Field label="Phone">
          <input
            className={inputClass}
            value={form.phone ?? ""}
            onChange={(e) => setForm({ ...form, phone: e.target.value })}
          />
        </Field>
        <div className="mt-2 flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? "Saving…" : "Create customer"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
