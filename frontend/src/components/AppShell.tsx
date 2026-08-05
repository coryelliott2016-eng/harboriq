import { NavLink, Outlet } from "react-router-dom";
import { useAuth, canManageOperations, canManageUsers } from "../context/AuthContext";

const navItems = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/customers", label: "Customers" },
  { to: "/jobs", label: "Jobs" },
  { to: "/dispatch", label: "Dispatch board" },
  { to: "/invoices", label: "Invoices" },
];

export function AppShell() {
  const { user, logout } = useAuth();

  return (
    <div className="flex min-h-screen bg-slate-50">
      <aside className="flex w-56 flex-shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="px-5 py-5">
          <span className="text-lg font-bold tracking-tight text-slate-900">HarborIQ</span>
        </div>
        <nav className="flex flex-1 flex-col gap-1 px-3">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `rounded-md px-3 py-2 text-sm font-medium ${
                  isActive
                    ? "bg-slate-900 text-white"
                    : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
          {canManageOperations(user?.role) && (
            <NavLink
              to="/reports/ar-aging"
              className={({ isActive }) =>
                `rounded-md px-3 py-2 text-sm font-medium ${
                  isActive
                    ? "bg-slate-900 text-white"
                    : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                }`
              }
            >
              AR aging
            </NavLink>
          )}
          {canManageOperations(user?.role) && (
            <NavLink
              to="/messages"
              className={({ isActive }) =>
                `rounded-md px-3 py-2 text-sm font-medium ${
                  isActive
                    ? "bg-slate-900 text-white"
                    : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                }`
              }
            >
              Messages
            </NavLink>
          )}
          {canManageUsers(user?.role) && (
            <NavLink
              to="/settings/billing"
              className={({ isActive }) =>
                `rounded-md px-3 py-2 text-sm font-medium ${
                  isActive
                    ? "bg-slate-900 text-white"
                    : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                }`
              }
            >
              Billing settings
            </NavLink>
          )}
          {canManageOperations(user?.role) && (
            <NavLink
              to="/team"
              className={({ isActive }) =>
                `rounded-md px-3 py-2 text-sm font-medium ${
                  isActive
                    ? "bg-slate-900 text-white"
                    : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                }`
              }
            >
              Team
            </NavLink>
          )}
        </nav>
      </aside>

      <div className="flex flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-slate-200 bg-white px-6 py-3">
          <span className="text-sm text-slate-500">
            {user?.role ? `${user.role[0]!.toUpperCase()}${user.role.slice(1)} workspace` : ""}
          </span>
          <div className="flex items-center gap-4">
            <div className="text-right text-sm">
              <p className="font-medium text-slate-900">{user?.full_name ?? user?.email}</p>
              <p className="text-xs uppercase tracking-wide text-slate-400">{user?.role}</p>
            </div>
            <button
              onClick={() => void logout()}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Log out
            </button>
          </div>
        </header>
        <main className="flex-1 px-6 py-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
