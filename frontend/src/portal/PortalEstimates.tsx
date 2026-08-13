import { useState } from "react";
import { money } from "../lib/format";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { portalApi } from "../lib/services";
import { ApiError, apiRequest } from "../lib/api";
import { Badge, Button, Card, EmptyState, ErrorBanner, Spinner } from "../components/ui";
import { PortalLayout, PORTAL_INVALID_LINK_MESSAGE } from "./PortalLayout";
import type { PortalEstimate } from "../types/api";

const STATUS_TONE: Record<string, "slate" | "green" | "amber" | "red" | "blue"> = {
  draft: "slate",
  sent: "blue",
  approved: "green",
  rejected: "red",
  expired: "slate",
};

export function PortalEstimates() {
  const { token } = useParams<{ token: string }>();

  const query = useQuery({
    queryKey: ["portal", token, "estimates"],
    queryFn: () => portalApi.estimates(token!),
    enabled: !!token,
    retry: false,
  });

  return (
    <PortalLayout>
      <h2 className="mb-4 text-lg font-semibold text-slate-900">Estimates</h2>

      {query.isLoading && <Spinner label="Loading your estimates…" />}

      {query.isError && (
        <ErrorBanner
          message={
            query.error instanceof ApiError && query.error.status === 404
              ? PORTAL_INVALID_LINK_MESSAGE
              : "Something went wrong loading your estimates. Please contact the shop."
          }
        />
      )}

      {query.isSuccess && query.data.length === 0 && (
        <EmptyState message="No estimates on file yet." />
      )}

      {query.isSuccess && query.data.length > 0 && (
        <div className="flex flex-col gap-3">
          {query.data.map((estimate) => (
            <EstimateRow key={estimate.id} token={token!} estimate={estimate} />
          ))}
        </div>
      )}
    </PortalLayout>
  );
}

function EstimateRow({ token, estimate }: { token: string; estimate: PortalEstimate }) {
  const [error, setError] = useState<string | null>(null);
  const [approved, setApproved] = useState(false);

  const approveMutation = useMutation({
    mutationFn: async () => {
      // `approve_path` is a full API path such as
      // "/api/v1/public/estimate/{token}/approve" -- strip the "/api/v1"
      // prefix `apiRequest` already adds, then POST to the SAME existing
      // public approval endpoint the standalone PublicInvoicePage-style
      // flow uses (no duplicate approval logic on the frontend either).
      const { approve_path } = await portalApi.estimateApproveToken(token, estimate.id);
      const relativePath = approve_path.replace(/^\/api\/v1/, "");
      return apiRequest(relativePath, {
        method: "POST",
        body: { estimate_pdf_version: "1" },
        anonymous: true,
      });
    },
    onSuccess: () => setApproved(true),
    onError: () => setError("Could not approve this estimate. Please contact the shop."),
  });

  const status = approved ? "approved" : estimate.status;
  const canApprove = !approved && (estimate.status === "sent" || estimate.status === "draft");

  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="font-medium text-slate-900">Estimate {estimate.id.slice(0, 8)}…</p>
          <p className="text-sm text-slate-500">Total {money(estimate.total)}</p>
        </div>
        <Badge tone={STATUS_TONE[status] ?? "slate"}>{status}</Badge>
      </div>
      {error && <p className="mt-2 text-sm text-red-700">{error}</p>}
      {canApprove && (
        <div className="mt-3">
          <Button onClick={() => approveMutation.mutate()} disabled={approveMutation.isPending}>
            {approveMutation.isPending ? "Approving…" : "Approve this estimate"}
          </Button>
        </div>
      )}
    </Card>
  );
}
