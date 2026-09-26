import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { estimatesApi } from "../lib/services";
import { ApiError } from "../lib/api";
import { money } from "../lib/format";
import { Badge, Button, Card, ErrorBanner, Field, Modal, Spinner, inputClass } from "./ui";
import type {
  Estimate,
  EstimateLineItemInput,
  EstimateLineKind,
  EstimateStatus,
} from "../types/api";

const STATUS_TONE: Record<EstimateStatus, "slate" | "green" | "amber" | "red" | "blue"> = {
  draft: "slate",
  sent: "blue",
  viewed: "blue",
  approved: "green",
  declined: "red",
  expired: "amber",
  invoiced: "green",
};

const STATUS_LABEL: Record<EstimateStatus, string> = {
  draft: "Draft",
  sent: "Sent — awaiting approval",
  viewed: "Viewed by customer",
  approved: "Approved",
  declined: "Declined",
  expired: "Expired",
  invoiced: "Invoiced",
};

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

/**
 * Estimates for one job: create a priced proposal (labor hours, parts,
 * diagnostic/haul-out fees), send it to the customer's portal for approval,
 * and convert an approved estimate into a draft invoice.
 */
export function JobEstimates({ jobId }: { jobId: string }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [showCreate, setShowCreate] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ["estimates", { job_id: jobId }],
    queryFn: () => estimatesApi.list({ job_id: jobId }),
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["estimates"] });

  const sendMutation = useMutation({
    mutationFn: (id: string) => estimatesApi.send(id),
    onSuccess: (res) => {
      setActionError(null);
      setNotice(
        res.email_queued
          ? "Estimate sent. The customer was emailed a portal link to review and approve it."
          : "Estimate marked as sent. This customer has no email on file — share their portal link from the customer page.",
      );
      invalidate();
    },
    onError: (err) => setActionError(errorMessage(err, "Failed to send estimate.")),
  });

  const convertMutation = useMutation({
    mutationFn: (id: string) => estimatesApi.convert(id),
    onSuccess: (res) => {
      invalidate();
      queryClient.invalidateQueries({ queryKey: ["jobs", jobId] });
      queryClient.invalidateQueries({ queryKey: ["invoices"] });
      navigate(`/invoices/${res.invoice_id}`);
    },
    onError: (err) => setActionError(errorMessage(err, "Failed to convert estimate.")),
  });

  return (
    <Card>
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <h2 className="text-sm font-semibold text-slate-900">Estimates</h2>
        <Button variant="secondary" onClick={() => setShowCreate(true)}>
          New estimate
        </Button>
      </div>

      <div className="flex flex-col gap-3 p-4">
        {actionError && <ErrorBanner message={actionError} />}
        {notice && (
          <p role="status" className="rounded-md bg-green-50 px-3 py-2 text-sm text-green-800">
            {notice}
          </p>
        )}

        {query.isLoading && <Spinner label="Loading estimates…" />}
        {query.isError && (
          <ErrorBanner message={errorMessage(query.error, "Failed to load estimates.")} />
        )}
        {query.isSuccess && query.data.length === 0 && (
          <p className="text-sm text-slate-500">
            No estimates yet. Create one to get the customer's approval before work starts.
          </p>
        )}

        {query.isSuccess &&
          query.data.map((estimate: Estimate) => (
            <div
              key={estimate.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-slate-200 px-3 py-2"
            >
              <div className="flex flex-col">
                <span className="text-sm font-medium text-slate-900">{money(estimate.total)}</span>
                <span className="text-xs text-slate-500">
                  Created {new Date(estimate.created_at).toLocaleDateString()}
                  {estimate.sent_at && ` · Sent ${new Date(estimate.sent_at).toLocaleDateString()}`}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <Badge tone={STATUS_TONE[estimate.status]}>{STATUS_LABEL[estimate.status]}</Badge>
                {estimate.status === "draft" && (
                  <Button
                    disabled={sendMutation.isPending}
                    onClick={() => sendMutation.mutate(estimate.id)}
                  >
                    {sendMutation.isPending ? "Sending…" : "Send to customer"}
                  </Button>
                )}
                {estimate.status === "approved" && (
                  <Button
                    disabled={convertMutation.isPending}
                    onClick={() => convertMutation.mutate(estimate.id)}
                  >
                    {convertMutation.isPending ? "Converting…" : "Convert to invoice"}
                  </Button>
                )}
              </div>
            </div>
          ))}
      </div>

      {showCreate && (
        <CreateEstimateModal
          jobId={jobId}
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setNotice("Draft estimate created. Review it, then send it to the customer.");
            invalidate();
          }}
        />
      )}
    </Card>
  );
}

const EMPTY_LINE: EstimateLineItemInput = {
  kind: "labor",
  description: "",
  quantity: "1",
  unit_price: "0",
  taxable: false,
};

const DIAGNOSTIC_FEE: EstimateLineItemInput = {
  kind: "fee",
  description: "Diagnostic fee",
  quantity: "1",
  unit_price: "0",
  taxable: false,
};

function lineTotal(line: EstimateLineItemInput): number {
  const q = Number(line.quantity);
  const p = Number(line.unit_price);
  return Number.isFinite(q) && Number.isFinite(p) ? Math.round(q * p * 100) / 100 : 0;
}

export function CreateEstimateModal({
  jobId,
  onClose,
  onCreated,
}: {
  jobId: string;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [lines, setLines] = useState<EstimateLineItemInput[]>([{ ...EMPTY_LINE }]);
  const [taxPercent, setTaxPercent] = useState("0");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);

  const subtotal = useMemo(() => lines.reduce((sum, l) => sum + lineTotal(l), 0), [lines]);

  const mutation = useMutation({
    mutationFn: () =>
      estimatesApi.create({
        job_id: jobId,
        tax_rate: (Number(taxPercent || "0") / 100).toFixed(4),
        notes: notes.trim() || null,
        line_items: lines,
      }),
    onSuccess: () => {
      onCreated();
      onClose();
    },
    onError: (err) => setError(errorMessage(err, "Failed to create estimate.")),
  });

  function update(index: number, patch: Partial<EstimateLineItemInput>) {
    setLines((prev) => prev.map((l, i) => (i === index ? { ...l, ...patch } : l)));
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const tax = Number(taxPercent || "0");
    if (!Number.isFinite(tax) || tax < 0 || tax > 100) {
      setError("Tax rate must be between 0 and 100 percent.");
      return;
    }
    mutation.mutate();
  }

  return (
    <Modal title="New estimate" onClose={onClose}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        {error && <ErrorBanner message={error} />}

        {lines.map((line, index) => (
          <fieldset
            key={index}
            className="flex flex-col gap-3 rounded-md border border-slate-200 p-3"
          >
            <legend className="px-1 text-xs font-medium text-slate-500">Line {index + 1}</legend>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Kind">
                <select
                  className={inputClass}
                  value={line.kind}
                  onChange={(e) => update(index, { kind: e.target.value as EstimateLineKind })}
                >
                  <option value="labor">Labor (hours)</option>
                  <option value="part">Part</option>
                  <option value="fee">Fee (diagnostic, haul-out, travel)</option>
                </select>
              </Field>
              <Field label="Description">
                <input
                  required
                  maxLength={500}
                  className={inputClass}
                  value={line.description}
                  onChange={(e) => update(index, { description: e.target.value })}
                />
              </Field>
              <Field label={line.kind === "labor" ? "Hours" : "Quantity"}>
                <input
                  required
                  type="number"
                  step="0.01"
                  min="0.01"
                  max="10000"
                  className={inputClass}
                  value={line.quantity}
                  onChange={(e) => update(index, { quantity: e.target.value })}
                />
              </Field>
              <Field label={line.kind === "labor" ? "Rate per hour" : "Unit price"}>
                <input
                  required
                  type="number"
                  step="0.01"
                  min="0"
                  max="100000"
                  className={inputClass}
                  value={line.unit_price}
                  onChange={(e) => update(index, { unit_price: e.target.value })}
                />
              </Field>
            </div>
            <div className="flex items-center justify-between text-sm">
              <label className="flex items-center gap-2 text-slate-700">
                <input
                  type="checkbox"
                  checked={line.taxable}
                  onChange={(e) => update(index, { taxable: e.target.checked })}
                />
                Taxable
              </label>
              <span className="text-slate-600">{money(lineTotal(line).toFixed(2))}</span>
              {lines.length > 1 && (
                <button
                  type="button"
                  className="text-xs text-red-600 hover:underline"
                  onClick={() => setLines((prev) => prev.filter((_, i) => i !== index))}
                >
                  Remove
                </button>
              )}
            </div>
          </fieldset>
        ))}

        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="secondary" onClick={() => setLines((p) => [...p, { ...EMPTY_LINE }])}>
            Add line
          </Button>
          <Button
            type="button"
            variant="secondary"
            onClick={() => setLines((p) => [...p, { ...DIAGNOSTIC_FEE }])}
          >
            Add diagnostic fee
          </Button>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Tax rate (%) on taxable lines">
            <input
              type="number"
              step="0.01"
              min="0"
              max="100"
              className={inputClass}
              value={taxPercent}
              onChange={(e) => setTaxPercent(e.target.value)}
            />
          </Field>
          <div className="flex flex-col justify-end text-right text-sm text-slate-700">
            <span>Subtotal before tax</span>
            <span className="text-base font-semibold text-slate-900">
              {money(subtotal.toFixed(2))}
            </span>
          </div>
        </div>

        <Field label="Notes for the customer (optional)">
          <textarea
            maxLength={2000}
            rows={2}
            className={inputClass}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </Field>

        <div className="mt-2 flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? "Saving…" : "Create draft estimate"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
