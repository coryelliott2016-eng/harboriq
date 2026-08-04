import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { billingApi } from "../lib/services";
import { ApiError } from "../lib/api";
import { Badge, Button, Card, ErrorBanner, Spinner } from "../components/ui";

// Owner/admin only (mirrors app/api/v1/routes/billing.py::require_admin) --
// gated at the route level in App.tsx, same pattern as TeamPage/TeamRoute.
//
// Stripe Connect Standard accounts let a tenant collect payments directly
// into their own Stripe account instead of the platform's single shared
// account. A tenant that has never onboarded keeps working exactly as
// before (checkout sessions fall back to the platform account) -- this page
// only ever *adds* a capability, it never blocks anything if skipped.
export function BillingSettingsPage() {
  const queryClient = useQueryClient();

  const statusQuery = useQuery({
    queryKey: ["billing", "connect-status"],
    queryFn: () => billingApi.connectStatus(),
  });

  const onboardMutation = useMutation({
    mutationFn: () => billingApi.connectOnboardingLink(),
    onSuccess: (resp) => {
      window.location.href = resp.onboarding_url;
    },
  });

  const dunningMutation = useMutation({
    mutationFn: () => billingApi.runDunning(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["invoices"] });
    },
  });

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Billing settings</h1>
        <p className="mt-1 text-sm text-slate-500">
          Connect your own Stripe account and manage overdue-invoice reminders.
        </p>
      </div>

      <Card className="max-w-lg p-5">
        <h2 className="text-sm font-semibold text-slate-900">Stripe Connect</h2>
        <p className="mt-1 text-xs text-slate-500">
          Onboard a Stripe Connect Standard account so customer payments settle directly
          to your own Stripe balance instead of the platform's shared account. This is
          optional — invoices keep working on the platform account until you connect.
        </p>

        {statusQuery.isLoading && <Spinner label="Checking connection status…" />}
        {statusQuery.isError && (
          <ErrorBanner
            message={
              statusQuery.error instanceof ApiError
                ? statusQuery.error.message
                : "Failed to load Stripe Connect status."
            }
          />
        )}

        {statusQuery.data && (
          <div className="mt-4 flex flex-col gap-3">
            <div className="flex items-center gap-2">
              <span className="text-sm text-slate-600">Status:</span>
              {statusQuery.data.connected ? (
                <Badge tone={statusQuery.data.charges_enabled ? "green" : "amber"}>
                  {statusQuery.data.charges_enabled ? "Connected" : "Onboarding incomplete"}
                </Badge>
              ) : (
                <Badge tone="slate">Not connected</Badge>
              )}
            </div>
            {statusQuery.data.account_id && (
              <p className="text-xs text-slate-400">Account: {statusQuery.data.account_id}</p>
            )}
            {onboardMutation.isError && (
              <ErrorBanner
                message={
                  onboardMutation.error instanceof ApiError
                    ? onboardMutation.error.message
                    : "Failed to start Stripe onboarding."
                }
              />
            )}
            <Button
              disabled={onboardMutation.isPending}
              onClick={() => onboardMutation.mutate()}
            >
              {onboardMutation.isPending
                ? "Starting…"
                : statusQuery.data.connected
                  ? "Continue onboarding"
                  : "Connect Stripe"}
            </Button>
          </div>
        )}
      </Card>

      <Card className="max-w-lg p-5">
        <h2 className="text-sm font-semibold text-slate-900">Overdue invoice reminders</h2>
        <p className="mt-1 text-xs text-slate-500">
          Dunning reminders normally go out automatically. Use this to trigger an
          on-demand sweep right now (respects the existing per-invoice cooldown, so
          running it repeatedly will not spam customers).
        </p>
        {dunningMutation.isError && (
          <ErrorBanner
            message={
              dunningMutation.error instanceof ApiError
                ? dunningMutation.error.message
                : "Failed to run the dunning sweep."
            }
          />
        )}
        {dunningMutation.isSuccess && (
          <p className="mt-3 rounded-md border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800">
            Reminded {dunningMutation.data.count} overdue invoice
            {dunningMutation.data.count === 1 ? "" : "s"}.
          </p>
        )}
        <Button
          className="mt-3"
          variant="secondary"
          disabled={dunningMutation.isPending}
          onClick={() => dunningMutation.mutate()}
        >
          {dunningMutation.isPending ? "Running…" : "Run dunning sweep now"}
        </Button>
      </Card>
    </div>
  );
}
