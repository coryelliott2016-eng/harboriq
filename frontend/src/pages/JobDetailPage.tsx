import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { dispatchApi, fieldApi, invoicesApi, jobsApi } from "../lib/services";
import { ApiError } from "../lib/api";
import { useAuth, canManageOperations } from "../context/AuthContext";
import {
  Badge,
  Button,
  Card,
  ErrorBanner,
  Field,
  Modal,
  Spinner,
  inputClass,
  money,
} from "../components/ui";
import { JOB_STATUS_LABELS, legalNextStatuses } from "../lib/jobStateMachine";
import { DispatchBreakdown } from "../components/DispatchBreakdown";
import type { JobLineItem, JobLineItemInput, JobLineItemKind, JobStatus } from "../types/api";

export function JobDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const canWrite = canManageOperations(user?.role);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [showAddLine, setShowAddLine] = useState(false);
  const [editingLineId, setEditingLineId] = useState<string | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [invoiceError, setInvoiceError] = useState<string | null>(null);

  const jobQuery = useQuery({
    queryKey: ["jobs", id],
    queryFn: () => jobsApi.get(id!),
    enabled: !!id,
  });

  const statusMutation = useMutation({
    mutationFn: (target: JobStatus) => jobsApi.setStatus(id!, target),
    onSuccess: () => {
      setStatusError(null);
      queryClient.invalidateQueries({ queryKey: ["jobs", id] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (err) => setStatusError(err instanceof ApiError ? err.message : "Failed to update status."),
  });

  const removeLineMutation = useMutation({
    mutationFn: (lineItemId: string) => jobsApi.removeLineItem(id!, lineItemId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["jobs", id] }),
  });

  const updateLineMutation = useMutation({
    mutationFn: ({ lineItemId, body }: { lineItemId: string; body: Partial<JobLineItemInput> }) =>
      jobsApi.updateLineItem(id!, lineItemId, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs", id] });
      setEditingLineId(null);
    },
  });

  const createInvoiceMutation = useMutation({
    mutationFn: () => invoicesApi.createFromJob(id!),
    onSuccess: (invoice) => {
      queryClient.invalidateQueries({ queryKey: ["jobs", id] });
      queryClient.invalidateQueries({ queryKey: ["invoices"] });
      navigate(`/invoices/${invoice.id}`);
    },
    onError: (err) => setInvoiceError(err instanceof ApiError ? err.message : "Failed to create invoice."),
  });

  if (!id) return <ErrorBanner message="Missing job id." />;
  if (jobQuery.isLoading) return <Spinner label="Loading job…" />;
  if (jobQuery.isError)
    return (
      <ErrorBanner message={jobQuery.error instanceof Error ? jobQuery.error.message : "Failed to load job."} />
    );

  const job = jobQuery.data!;
  const nextStatuses = legalNextStatuses(job.status);
  const uninvoicedLines = job.line_items.filter((li) => !li.invoice_id);
  const canCreateInvoice = canWrite && uninvoicedLines.length > 0;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link to="/jobs" className="text-sm text-slate-500 hover:underline">
          ← All jobs
        </Link>
        <div className="mt-1 flex items-center gap-3">
          <h1 className="text-2xl font-semibold text-slate-900">{job.title}</h1>
          <Badge tone={job.status === "completed" ? "green" : job.status === "canceled" ? "red" : "blue"}>
            {JOB_STATUS_LABELS[job.status]}
          </Badge>
        </div>
        {job.description && <p className="mt-1 text-sm text-slate-500">{job.description}</p>}
      </div>

      {statusError && <ErrorBanner message={statusError} />}

      {canWrite && nextStatuses.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-slate-500">Move to:</span>
          {nextStatuses.map((s) => (
            <Button
              key={s}
              variant="secondary"
              disabled={statusMutation.isPending}
              onClick={() => statusMutation.mutate(s)}
            >
              {JOB_STATUS_LABELS[s]}
            </Button>
          ))}
        </div>
      )}

      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-900">Line items</h2>
        {canWrite && <Button onClick={() => setShowAddLine(true)}>Add line item</Button>}
      </div>

      <Card>
        {job.line_items.length === 0 ? (
          <p className="px-4 py-6 text-center text-sm text-slate-500">No line items recorded yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="border-b border-slate-100 text-left text-xs uppercase text-slate-400">
              <tr>
                <th className="px-4 py-2">Description</th>
                <th className="px-4 py-2">Kind</th>
                <th className="px-4 py-2 text-right">Qty</th>
                <th className="px-4 py-2 text-right">Unit price</th>
                <th className="px-4 py-2 text-right">Total</th>
                <th className="px-4 py-2">Invoiced</th>
                {canWrite && <th className="px-4 py-2" />}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {job.line_items.map((li) =>
                editingLineId === li.id ? (
                  <EditLineItemRow
                    key={li.id}
                    lineItem={li}
                    saving={updateLineMutation.isPending}
                    onCancel={() => setEditingLineId(null)}
                    onSave={(body) => updateLineMutation.mutate({ lineItemId: li.id, body })}
                  />
                ) : (
                  <tr key={li.id}>
                    <td className="px-4 py-2">{li.description}</td>
                    <td className="px-4 py-2 capitalize">{li.kind}</td>
                    <td className="px-4 py-2 text-right">{li.quantity}</td>
                    <td className="px-4 py-2 text-right">{money(li.unit_price)}</td>
                    <td className="px-4 py-2 text-right">{money(li.line_total)}</td>
                    <td className="px-4 py-2">
                      {li.invoice_id ? (
                        <Badge tone="green">Invoiced</Badge>
                      ) : (
                        <Badge tone="slate">Uninvoiced</Badge>
                      )}
                    </td>
                    {canWrite && (
                      <td className="px-4 py-2 text-right">
                        {!li.invoice_id && (
                          <div className="flex justify-end gap-3">
                            <button
                              className="text-xs text-slate-600 hover:underline"
                              onClick={() => setEditingLineId(li.id)}
                            >
                              Edit
                            </button>
                            <button
                              className="text-xs text-red-600 hover:underline"
                              onClick={() => removeLineMutation.mutate(li.id)}
                            >
                              Remove
                            </button>
                          </div>
                        )}
                      </td>
                    )}
                  </tr>
                ),
              )}
            </tbody>
          </table>
        )}
      </Card>

      {canWrite && <DispatchSuggestions jobId={id} technicianId={job.technician_id} />}

      <FieldAppActivity jobId={id} />

      {invoiceError && <ErrorBanner message={invoiceError} />}

      {canWrite && (
        <div>
          <Button disabled={!canCreateInvoice || createInvoiceMutation.isPending} onClick={() => createInvoiceMutation.mutate()}>
            {createInvoiceMutation.isPending ? "Creating invoice…" : "Create invoice"}
          </Button>
          {!canCreateInvoice && (
            <p className="mt-2 text-xs text-slate-400">
              Add at least one uninvoiced line item before creating an invoice.
            </p>
          )}
        </div>
      )}

      {showAddLine && <AddLineItemModal jobId={id} onClose={() => setShowAddLine(false)} />}
    </div>
  );
}

function EditLineItemRow({
  lineItem,
  saving,
  onCancel,
  onSave,
}: {
  lineItem: JobLineItem;
  saving: boolean;
  onCancel: () => void;
  onSave: (body: Partial<JobLineItemInput>) => void;
}) {
  const [description, setDescription] = useState(lineItem.description);
  const [quantity, setQuantity] = useState(lineItem.quantity);
  const [unitPrice, setUnitPrice] = useState(lineItem.unit_price);
  const [taxable, setTaxable] = useState(lineItem.taxable);

  function handleSave() {
    onSave({ description, quantity, unit_price: unitPrice, taxable });
  }

  return (
    <tr className="bg-slate-50">
      <td className="px-4 py-2">
        <input
          className={inputClass}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </td>
      <td className="px-4 py-2 capitalize text-slate-400">{lineItem.kind}</td>
      <td className="px-4 py-2">
        <input
          type="number"
          step="0.01"
          min="0.01"
          className={`${inputClass} text-right`}
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
        />
      </td>
      <td className="px-4 py-2">
        <input
          type="number"
          step="0.01"
          min="0"
          className={`${inputClass} text-right`}
          value={unitPrice}
          onChange={(e) => setUnitPrice(e.target.value)}
        />
      </td>
      <td className="px-4 py-2 text-right text-slate-400">—</td>
      <td className="px-4 py-2">
        <label className="flex items-center gap-1.5 text-xs text-slate-600">
          <input type="checkbox" checked={taxable} onChange={(e) => setTaxable(e.target.checked)} />
          Taxable
        </label>
      </td>
      <td className="px-4 py-2 text-right">
        <div className="flex justify-end gap-3">
          <button className="text-xs text-slate-500 hover:underline" onClick={onCancel} disabled={saving}>
            Cancel
          </button>
          <button className="text-xs font-medium text-blue-600 hover:underline" onClick={handleSave} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </td>
    </tr>
  );
}

function AddLineItemModal({ jobId, onClose }: { jobId: string; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [kind, setKind] = useState<JobLineItemKind>("labor");
  const [description, setDescription] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [unitPrice, setUnitPrice] = useState("0");
  const [taxable, setTaxable] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => {
      const body: JobLineItemInput = { kind, description, quantity, unit_price: unitPrice, taxable };
      return jobsApi.addLineItem(jobId, body);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs", jobId] });
      onClose();
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : "Failed to add line item."),
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    mutation.mutate();
  }

  return (
    <Modal title="Add line item" onClose={onClose}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        {error && <ErrorBanner message={error} />}
        <Field label="Kind">
          <select className={inputClass} value={kind} onChange={(e) => setKind(e.target.value as JobLineItemKind)}>
            <option value="labor">Labor</option>
            <option value="part">Part</option>
            <option value="fee">Fee</option>
          </select>
        </Field>
        <Field label="Description">
          <input
            required
            className={inputClass}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Quantity">
            <input
              required
              type="number"
              step="0.01"
              min="0.01"
              className={inputClass}
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
            />
          </Field>
          <Field label="Unit price">
            <input
              required
              type="number"
              step="0.01"
              min="0"
              className={inputClass}
              value={unitPrice}
              onChange={(e) => setUnitPrice(e.target.value)}
            />
          </Field>
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" checked={taxable} onChange={(e) => setTaxable(e.target.checked)} />
          Taxable
        </label>
        <div className="mt-2 flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? "Saving…" : "Add line item"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

/**
 * The AI dispatch engine's ranked technician suggestions for this job (see
 * app/services/dispatch.py::rank_technicians_for_job). Operations roles only
 * (gated by the caller via `canWrite`/`require_operations` server-side).
 * Fetched on demand rather than automatically, since ranking every
 * technician is a heavier query than the rest of the page and is only
 * useful once someone is actually deciding who to dispatch.
 */
function DispatchSuggestions({
  jobId,
  technicianId,
}: {
  jobId: string;
  technicianId: string | null;
}) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [assignError, setAssignError] = useState<string | null>(null);

  const candidatesQuery = useQuery({
    queryKey: ["jobs", jobId, "dispatch", "candidates"],
    queryFn: () => dispatchApi.candidates(jobId),
    enabled: expanded,
  });

  const assignMutation = useMutation({
    mutationFn: (candidateId: string) => jobsApi.assign(jobId, candidateId),
    onSuccess: () => {
      setAssignError(null);
      queryClient.invalidateQueries({ queryKey: ["jobs", jobId] });
      queryClient.invalidateQueries({ queryKey: ["jobs", jobId, "dispatch", "candidates"] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (err) => setAssignError(err instanceof ApiError ? err.message : "Failed to assign."),
  });

  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-900">Dispatch suggestions</h2>
        <Button variant="secondary" onClick={() => setExpanded((v) => !v)}>
          {expanded ? "Hide" : "Show suggestions"}
        </Button>
      </div>
      {expanded && (
        <div className="mt-4 flex flex-col gap-3">
          {assignError && <ErrorBanner message={assignError} />}
          {candidatesQuery.isLoading && <Spinner label="Ranking technicians…" />}
          {candidatesQuery.isError && (
            <ErrorBanner
              message={
                candidatesQuery.error instanceof Error
                  ? candidatesQuery.error.message
                  : "Failed to load dispatch candidates."
              }
            />
          )}
          {candidatesQuery.data && candidatesQuery.data.length === 0 && (
            <p className="text-sm text-slate-500">No active technicians available to dispatch.</p>
          )}
          {candidatesQuery.data?.map((candidate) => (
            <div
              key={candidate.technician_id}
              className="flex items-center justify-between gap-4 rounded-md border border-slate-100 px-3 py-2"
            >
              <div className="flex flex-col gap-1">
                <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
                  {candidate.technician_name}
                  {candidate.technician_id === technicianId && <Badge tone="green">Assigned</Badge>}
                </div>
                <DispatchBreakdown score={candidate.score} />
              </div>
              <Button
                variant="secondary"
                disabled={candidate.technician_id === technicianId || assignMutation.isPending}
                onClick={() => assignMutation.mutate(candidate.technician_id)}
              >
                Assign
              </Button>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

/**
 * Staff-side visibility (Phase 12 spec requirement) into what the field app
 * has captured for this job: photos/signatures uploaded by technicians and
 * their clock in/out history. Read-only here -- capture only happens from
 * the field app itself (see FieldPage.tsx).
 */
function FieldAppActivity({ jobId }: { jobId: string }) {
  const attachmentsQuery = useQuery({
    queryKey: ["jobs", jobId, "attachments"],
    queryFn: () => fieldApi.attachments(jobId),
  });
  const timeEntriesQuery = useQuery({
    queryKey: ["jobs", jobId, "time-entries"],
    queryFn: () => fieldApi.timeEntries(jobId),
  });

  // Lazy useState initializer (runs once at mount, not on every render) --
  // calling Date.now() directly in the component body is flagged as an
  // impure render by the react-hooks/purity rule. "Still clocked in"
  // durations are therefore accurate as of when this card first mounted,
  // not live-ticking -- acceptable for a staff-side summary view.
  const [renderedAt] = useState(() => Date.now());

  function formatDuration(clockedInAt: string, clockedOutAt: string | null): string {
    const start = new Date(clockedInAt).getTime();
    const end = clockedOutAt ? new Date(clockedOutAt).getTime() : renderedAt;
    const minutes = Math.max(0, Math.round((end - start) / 60000));
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    return hours > 0 ? `${hours}h ${mins}m` : `${mins}m`;
  }

  return (
    <Card className="flex flex-col gap-4 p-4">
      <h2 className="text-lg font-semibold text-slate-900">Field app activity</h2>

      <div>
        <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Photos &amp; signatures
        </h3>
        {attachmentsQuery.isLoading && <Spinner label="Loading attachments…" />}
        {attachmentsQuery.isSuccess && attachmentsQuery.data.length === 0 && (
          <p className="mt-2 text-sm text-slate-400">No attachments captured yet.</p>
        )}
        {attachmentsQuery.isSuccess && attachmentsQuery.data.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-3">
            {attachmentsQuery.data.map((att) => (
              <div key={att.id} className="flex flex-col items-center gap-1">
                {att.data ? (
                  <img
                    src={`data:${att.content_type};base64,${att.data}`}
                    alt={att.kind}
                    className="h-24 w-24 rounded-md border border-slate-200 object-cover"
                  />
                ) : (
                  <div className="flex h-24 w-24 items-center justify-center rounded-md border border-slate-200 text-xs text-slate-400">
                    No preview
                  </div>
                )}
                <Badge tone={att.kind === "signature" ? "blue" : "slate"}>{att.kind}</Badge>
              </div>
            ))}
          </div>
        )}
      </div>

      <div>
        <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Time clock</h3>
        {timeEntriesQuery.isLoading && <Spinner label="Loading time entries…" />}
        {timeEntriesQuery.isSuccess && timeEntriesQuery.data.length === 0 && (
          <p className="mt-2 text-sm text-slate-400">No time entries recorded yet.</p>
        )}
        {timeEntriesQuery.isSuccess && timeEntriesQuery.data.length > 0 && (
          <table className="mt-2 w-full text-sm">
            <thead className="border-b border-slate-100 text-left text-xs uppercase text-slate-400">
              <tr>
                <th className="py-1.5 pr-4">Clocked in</th>
                <th className="py-1.5 pr-4">Clocked out</th>
                <th className="py-1.5">Duration</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {timeEntriesQuery.data.map((entry) => (
                <tr key={entry.id}>
                  <td className="py-1.5 pr-4">{new Date(entry.clocked_in_at).toLocaleString()}</td>
                  <td className="py-1.5 pr-4">
                    {entry.clocked_out_at ? (
                      new Date(entry.clocked_out_at).toLocaleString()
                    ) : (
                      <Badge tone="blue">Still clocked in</Badge>
                    )}
                  </td>
                  <td className="py-1.5">{formatDuration(entry.clocked_in_at, entry.clocked_out_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Card>
  );
}
