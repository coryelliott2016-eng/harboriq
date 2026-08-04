import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { portalApi } from "../lib/services";
import { ApiError } from "../lib/api";
import { Card, ErrorBanner, Spinner } from "../components/ui";
import { PortalLayout, PORTAL_INVALID_LINK_MESSAGE } from "./PortalLayout";

export function PortalHome() {
  const { token } = useParams<{ token: string }>();

  const query = useQuery({
    queryKey: ["portal", token, "me"],
    queryFn: () => portalApi.me(token!),
    enabled: !!token,
    retry: false,
  });

  return (
    <PortalLayout>
      {query.isLoading && <Spinner label="Loading your profile…" />}

      {query.isError && (
        <ErrorBanner
          message={
            query.error instanceof ApiError && query.error.status === 404
              ? PORTAL_INVALID_LINK_MESSAGE
              : "Something went wrong loading your account. Please contact the shop."
          }
        />
      )}

      {query.isSuccess && (
        <div className="flex flex-col gap-6">
          <Card className="p-5">
            <h2 className="text-lg font-semibold text-slate-900">
              Welcome{query.data.first_name ? `, ${query.data.first_name}` : ""}
            </h2>
            <dl className="mt-3 grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-xs uppercase text-slate-400">Email</dt>
                <dd className="text-slate-900">{query.data.email ?? "—"}</dd>
              </div>
              <div>
                <dt className="text-xs uppercase text-slate-400">Phone</dt>
                <dd className="text-slate-900">{query.data.phone ?? "—"}</dd>
              </div>
            </dl>
          </Card>

          <div>
            <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
              Your vessels
            </h3>
            {query.data.vessels.length === 0 && (
              <p className="text-sm text-slate-500">No vessels on file yet.</p>
            )}
            {query.data.vessels.length > 0 && (
              <Card>
                <ul className="divide-y divide-slate-100">
                  {query.data.vessels.map((v) => (
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
          </div>
        </div>
      )}
    </PortalLayout>
  );
}
