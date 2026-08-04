import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { portalApi } from "../lib/services";
import { ApiError } from "../lib/api";
import { Badge, Button, Card, EmptyState, ErrorBanner, Spinner, money } from "../components/ui";
import { PortalLayout, PORTAL_INVALID_LINK_MESSAGE } from "./PortalLayout";
import type { InvoiceStatus, PortalInvoice } from "../types/api";

const STATUS_TONE: Record<InvoiceStatus, "slate" | "green" | "amber" | "red" | "blue"> = {
  draft: "slate",
  sent: "blue",
  partial: "amber",
  paid: "green",
  void: "slate",
  uncollectible: "red",
  refunded: "slate",
  partially_refunded: "amber",
};

export function PortalInvoices() {
  const { token } = useParams<{ token: string }>();

  const query = useQuery({
    queryKey: ["portal", token, "invoices"],
    queryFn: () => portalApi.invoices(token!),
    enabled: !!token,
    retry: false,
  });

  return (
    <PortalLayout>
      <h2 className="mb-4 text-lg font-semibold text-slate-900">Invoices</h2>

      {query.isLoading && <Spinner label="Loading your invoices…" />}

      {query.isError && (
        <ErrorBanner
          message={
            query.error instanceof ApiError && query.error.status === 404
              ? PORTAL_INVALID_LINK_MESSAGE
              : "Something went wrong loading your invoices. Please contact the shop."
          }
        />
      )}

      {query.isSuccess && query.data.length === 0 && (
        <EmptyState message="No invoices on file yet." />
      )}

      {query.isSuccess && query.data.length > 0 && (
        <div className="flex flex-col gap-3">
          {query.data.map((invoice) => (
            <InvoiceRow key={invoice.id} token={token!} invoice={invoice} />
          ))}
        </div>
      )}
    </PortalLayout>
  );
}

function InvoiceRow({ token, invoice }: { token: string; invoice: PortalInvoice }) {
  const [payError, setPayError] = useState<string | null>(null);

  const payMutation = useMutation({
    mutationFn: () => portalApi.invoicePayUrl(token, invoice.id),
    onSuccess: (data) => {
      if (data.checkout_url) {
        window.location.assign(data.checkout_url);
      } else {
        setPayError("Online payment is temporarily unavailable. Please contact the shop.");
      }
    },
    onError: () => setPayError("Could not start payment. Please contact the shop."),
  });

  const payable = invoice.status !== "paid" && invoice.status !== "void";

  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="font-medium text-slate-900">Invoice {invoice.id.slice(0, 8)}…</p>
          <p className="text-sm text-slate-500">Total {money(invoice.total)} · Balance due {money(invoice.balance_due)}</p>
        </div>
        <Badge tone={STATUS_TONE[invoice.status]}>{invoice.status.replace("_", " ")}</Badge>
      </div>
      {payError && <p className="mt-2 text-sm text-red-700">{payError}</p>}
      {payable && (
        <div className="mt-3">
          <Button onClick={() => payMutation.mutate()} disabled={payMutation.isPending}>
            {payMutation.isPending ? "Redirecting…" : `Pay ${money(invoice.balance_due)} now`}
          </Button>
        </div>
      )}
    </Card>
  );
}
