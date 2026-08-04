import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { publicApi } from "../lib/services";
import { ApiError } from "../lib/api";
import { Card, ErrorBanner, Spinner, money } from "../components/ui";

export function PublicInvoicePage() {
  const { token } = useParams<{ token: string }>();

  const query = useQuery({
    queryKey: ["public-invoice", token],
    queryFn: () => publicApi.getInvoice(token!),
    enabled: !!token,
    retry: false,
  });

  return (
    <div className="min-h-screen bg-slate-50 px-4 py-10">
      <div className="mx-auto max-w-lg">
        <h1 className="mb-6 text-center text-xl font-semibold text-slate-900">HarborIQ</h1>

        {query.isLoading && <Spinner label="Loading your invoice…" />}

        {query.isError && (
          <ErrorBanner
            message={
              query.error instanceof ApiError && query.error.status === 404
                ? "This invoice link is invalid or has expired."
                : "Something went wrong loading this invoice. Please contact the shop."
            }
          />
        )}

        {query.isSuccess && (
          <Card className="p-6">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-slate-900">Invoice {query.data.id.slice(0, 8)}…</h2>
              <StatusPill status={query.data.status} />
            </div>

            <table className="w-full text-sm">
              <thead className="border-b border-slate-100 text-left text-xs uppercase text-slate-400">
                <tr>
                  <th className="py-2">Description</th>
                  <th className="py-2 text-right">Qty</th>
                  <th className="py-2 text-right">Total</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {query.data.line_items.map((li) => (
                  <tr key={li.id}>
                    <td className="py-2">{li.description}</td>
                    <td className="py-2 text-right">{li.quantity}</td>
                    <td className="py-2 text-right">{money(li.line_total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <dl className="mt-4 flex flex-col gap-1.5 border-t border-slate-100 pt-4 text-sm">
              <div className="flex justify-between">
                <dt className="text-slate-500">Subtotal</dt>
                <dd>{money(query.data.subtotal)}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-slate-500">Tax</dt>
                <dd>{money(query.data.tax_total)}</dd>
              </div>
              <div className="flex justify-between text-base font-semibold text-slate-900">
                <dt>Total</dt>
                <dd>{money(query.data.total)}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-slate-500">Balance due</dt>
                <dd>{money(query.data.balance_due)}</dd>
              </div>
            </dl>

            <div className="mt-6">
              <PaymentAction
                status={query.data.status}
                checkoutUrl={query.data.checkout_url}
                balanceDue={query.data.balance_due}
              />
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const tone =
    status === "paid"
      ? "bg-green-100 text-green-800"
      : status === "void" || status === "uncollectible"
        ? "bg-red-100 text-red-800"
        : "bg-slate-100 text-slate-700";
  return <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${tone}`}>{status}</span>;
}

function PaymentAction({
  status,
  checkoutUrl,
  balanceDue,
}: {
  status: string;
  checkoutUrl: string | null;
  balanceDue: string;
}) {
  if (status === "paid") {
    return (
      <p className="rounded-md bg-green-50 px-4 py-3 text-center text-sm font-medium text-green-800">
        This invoice has been paid in full. Thank you!
      </p>
    );
  }
  if (status === "void") {
    return (
      <p className="rounded-md bg-slate-100 px-4 py-3 text-center text-sm text-slate-600">
        This invoice has been voided. No payment is due.
      </p>
    );
  }
  if (checkoutUrl) {
    return (
      <a
        href={checkoutUrl}
        className="block w-full rounded-md bg-slate-900 px-4 py-2.5 text-center text-sm font-semibold text-white hover:bg-slate-700"
      >
        Pay {money(balanceDue)} now
      </a>
    );
  }
  return (
    <p className="rounded-md bg-amber-50 px-4 py-3 text-center text-sm text-amber-800">
      Online payment is temporarily unavailable. Please contact the shop to pay this invoice.
    </p>
  );
}
