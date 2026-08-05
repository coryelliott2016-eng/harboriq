import type { ReactNode } from "react";
import { NavLink, useParams } from "react-router-dom";

/**
 * Shared shell for every /portal/:token/* page — deliberately isolated from
 * the staff `AppShell`/nav (no auth context, no staff routes). Every nav
 * link keeps the same `:token` segment so the magic link stays in the URL
 * as the customer moves between tabs.
 */
export function PortalLayout({ children }: { children: ReactNode }) {
  const { token } = useParams<{ token: string }>();

  const navItems = [
    { to: `/portal/${token}`, label: "Overview", end: true },
    { to: `/portal/${token}/jobs`, label: "Jobs" },
    { to: `/portal/${token}/invoices`, label: "Invoices" },
    { to: `/portal/${token}/estimates`, label: "Estimates" },
    { to: `/portal/${token}/messages`, label: "Messages" },
    { to: `/portal/${token}/dock`, label: "Find my dock" },
  ];

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-3xl px-4 py-4">
          <h1 className="text-lg font-semibold text-slate-900">HarborIQ</h1>
          <nav className="mt-3 flex gap-1 overflow-x-auto">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium ${
                    isActive
                      ? "bg-slate-900 text-white"
                      : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-4 py-6">{children}</main>
    </div>
  );
}

/** Shared "this link doesn't work" message for an invalid/expired/revoked
 * portal token — matches PublicInvoicePage's tone for the same 404 case. */
export const PORTAL_INVALID_LINK_MESSAGE =
  "This link is invalid or has expired. Please contact the shop for a new one.";
