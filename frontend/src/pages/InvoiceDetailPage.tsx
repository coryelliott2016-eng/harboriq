import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { invoicesApi } from "../lib/services";
import { ApiError } from "../lib/api";
import { Badge, Button, Card, ErrorBanner, Spinner } from "../components/ui";
import { money } from "../lib/format";
import { INVOICE_STATUS_LABELS, canRefund, canSend, canVoid } from "../lib/invoiceStateMachine";

function statusTone(status: string) {
  if (status === "paid") return "green" as const;
  if (status === "void" || status === "uncollectible") return "red" as const;
  if (status === "partial" || status === "partially_refunded") return "amber" as const;
  if (status === "refunded") return "blue" as const;
  return "slate" as const;
}

export function InvoiceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const [actionError, setActionError] = useState<string | null>(null);
  const [payUrl, setPayUrl] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [refundOpen, setRefundOpen] = useState(false);
  const [refundAmount, setRefundAmount] = useState("");
  const [refundReason, setRefundReason] = useState("");
  const [refundNotice, setRefundNotice] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ["invoices", id],
    queryFn: () => invoicesApi.get(id!),
    enabled: !!id,
  });

  const sendMutation = useMutation({
    mutationFn: () => invoicesApi.send(id!),
    onSuccess: (resp) => {
      setActionError(null);
      // The backend's `pay_url` field points at its own API path
      // (`/api/v1/public/invoice/{token}`), which is meant for server-to-
      // server / direct API use — not something a customer should ever open
      // in a browser. The customer-facing link is our own SPA route, which
      // in turn calls that API. Build it from `pay_token` instead.
      // Router-aware: under VITE_ROUTER=hash (proxied staging hosts) the SPA
      // route lives in the fragment, anchored at the current document path.
      setPayUrl(
        import.meta.env.VITE_ROUTER === "hash"
          ? `${window.location.origin}${window.location.pathname}#/pay/${resp.pay_token}`
          : `${window.location.origin}/pay/${resp.pay_token}`,
      );
      queryClient.invalidateQueries({ queryKey: ["invoices", id] });
      queryClient.invalidateQueries({ queryKey: ["invoices"] });
    },
    onError: (err) => setActionError(err instanceof ApiError ? err.message : "Failed to send invoice."),
  });

  const voidMutation = useMutation({
    mutationFn: () => invoicesApi.void(id!),
    onSuccess: () => {
      setActionError(null);
      queryClient.invalidateQueries({ queryKey: ["invoices", id] });
      queryClient.invalidateQueries({ queryKey: ["invoices"] });
    },
    onError: (err) => setActionError(err instanceof ApiError ? err.message : "Failed to void invoice."),
  });

  const refundMutation = useMutation({
    mutationFn: () =>
      invoicesApi.refund(id!, {
        amount: refundAmount.trim() ? refundAmount.trim() : undefined,
        reason: refundReason.trim() ? refundReason.trim() : undefined,
      }),
    onSuccess: (resp) => {
      setActionError(null);
      setRefundOpen(false);
      setRefundAmount("");
      setRefundReason("");
      setRefundNotice(`Refunded ${money(resp.refund.amount)}.`);
      queryClient.invalidateQueries({ queryKey: ["invoices", id] });
      queryClient.invalidateQueries({ queryKey: ["invoices"] });
    },
    onError: (err) => setActionError(err instanceof ApiError ? err.message : "Failed to refund invoice."),
  });

  if (!id) return <ErrorBanner message="Missing invoice id." />;
  if (query.isLoading) return <Spinner label="Loading invoice…" />;
  if (query.isError)
    return <ErrorBanner message={query.error instanceof Error ? query.error.message : "Failed to load invoice."} />;

  const invoice = query.data!;

  function openRefundForm() {
    setActionError(null);
    setRefundNotice(null);
    // Default to the full remaining paid amount; the backend computes the
    // real refundable ceiling (amount_paid minus any refunds already
    // issued) and rejects anything over it, so this is only a starting
    // suggestion for the operator, not the source of truth.
    setRefundAmount(invoice.amount_paid);
    setRefundReason("");
    setRefundOpen(true);
  }

  async function copyPayUrl() {
    if (!payUrl) return;
    await navigator.clipboard.writeText(payUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link to="/invoices" className="text-sm text-slate-500 hover:underline">
          ← All invoices
        </Link>
        <div className="mt-1 flex items-center gap-3">
          <h1 className="text-2xl font-semibold text-slate-900">Invoice {invoice.id.slice(0, 8)}…</h1>
          <Badge tone={statusTone(invoice.status)}>{INVOICE_STATUS_LABELS[invoice.status]}</Badge>
        </div>
      </div>

      {actionError && <ErrorBanner message={actionError} />}
      {refundNotice && !actionError && (
        <div className="rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">
          {refundNotice}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {canSend(invoice.status) && (
          <Button disabled={sendMutation.isPending} onClick={() => sendMutation.mutate()}>
            {sendMutation.isPending ? "Sending…" : "Send invoice"}
          </Button>
        )}
        {canVoid(invoice.status) && (
          <Button variant="danger" disabled={voidMutation.isPending} onClick={() => voidMutation.mutate()}>
            {voidMutation.isPending ? "Voiding…" : "Void invoice"}
          </Button>
        )}
        {canRefund(invoice.status) && !refundOpen && (
          <Button variant="secondary" onClick={openRefundForm}>
            Refund
          </Button>
        )}
      </div>

      {refundOpen && (
        <Card className="max-w-md p-5">
          <h2 className="text-sm font-semibold text-slate-900">Issue a refund</h2>
          <p className="mt-1 text-xs text-slate-500">
            Leave the amount blank for a full refund of whatever remains refundable.
          </p>
          <form
            className="mt-4 flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              refundMutation.mutate();
            }}
          >
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-slate-700">Amount (USD)</span>
              <input
                type="number"
                min="0.01"
                step="0.01"
                className="rounded-md border border-slate-300 px-3 py-1.5 text-sm shadow-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
                value={refundAmount}
                onChange={(e) => setRefundAmount(e.target.value)}
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-slate-700">Reason (optional)</span>
              <input
                className="rounded-md border border-slate-300 px-3 py-1.5 text-sm shadow-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
                value={refundReason}
                onChange={(e) => setRefundReason(e.target.value)}
              />
            </label>
            <div className="flex gap-2">
              <Button type="submit" variant="danger" disabled={refundMutation.isPending}>
                {refundMutation.isPending ? "Refunding…" : "Confirm refund"}
              </Button>
              <Button type="button" variant="secondary" onClick={() => setRefundOpen(false)}>
                Cancel
              </Button>
            </div>
          </form>
        </Card>
      )}

      {payUrl && (
        <Card className="flex items-center justify-between gap-4 px-4 py-3">
          <div>
            <p className="text-xs uppercase text-slate-400">Pay link</p>
            <p className="break-all text-sm text-slate-900">{payUrl}</p>
          </div>
          <Button variant="secondary" onClick={() => void copyPayUrl()}>
            {copied ? "Copied!" : "Copy link"}
          </Button>
        </Card>
      )}

      <Card>
        <table className="w-full text-sm">
          <thead className="border-b border-slate-100 text-left text-xs uppercase text-slate-400">
            <tr>
              <th className="px-4 py-2">Description</th>
              <th className="px-4 py-2 text-right">Qty</th>
              <th className="px-4 py-2 text-right">Unit price</th>
              <th className="px-4 py-2 text-right">Total</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {invoice.line_items.map((li) => (
              <tr key={li.id}>
                <td className="px-4 py-2">{li.description}</td>
                <td className="px-4 py-2 text-right">{li.quantity}</td>
                <td className="px-4 py-2 text-right">{money(li.unit_price)}</td>
                <td className="px-4 py-2 text-right">{money(li.line_total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card className="ml-auto w-full max-w-xs px-5 py-4 text-sm">
        <dl className="flex flex-col gap-1.5">
          <div className="flex justify-between">
            <dt className="text-slate-500">Subtotal</dt>
            <dd>{money(invoice.subtotal)}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-slate-500">Tax</dt>
            <dd>{money(invoice.tax_total)}</dd>
          </div>
          <div className="flex justify-between font-semibold">
            <dt>Total</dt>
            <dd>{money(invoice.total)}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-slate-500">Paid</dt>
            <dd>{money(invoice.amount_paid)}</dd>
          </div>
          <div className="flex justify-between font-semibold text-slate-900">
            <dt>Balance due</dt>
            <dd>{money(invoice.balance_due)}</dd>
          </div>
        </dl>
      </Card>
    </div>
  );
}
