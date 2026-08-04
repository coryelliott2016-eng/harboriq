import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { canManageUsers, useAuth } from "./context/AuthContext";
import { AcceptInvitePage } from "./pages/AcceptInvitePage";
import { CustomerDetailPage } from "./pages/CustomerDetailPage";
import { CustomersPage } from "./pages/CustomersPage";
import { DashboardPage } from "./pages/DashboardPage";
import { InvoiceDetailPage } from "./pages/InvoiceDetailPage";
import { InvoicesPage } from "./pages/InvoicesPage";
import { JobDetailPage } from "./pages/JobDetailPage";
import { JobsPage } from "./pages/JobsPage";
import { LoginPage } from "./pages/LoginPage";
import { PublicInvoicePage } from "./pages/PublicInvoicePage";
import { SignupPage } from "./pages/SignupPage";
import { TeamPage } from "./pages/TeamPage";

function TeamRoute() {
  const { user } = useAuth();
  if (!canManageUsers(user?.role)) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        You don't have permission to view this page. Team management is limited to
        owners and admins.
      </div>
    );
  }
  return <TeamPage />;
}

export default function App() {
  return (
    <Routes>
      {/* Unauthenticated */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
      <Route path="/pay/:token" element={<PublicInvoicePage />} />
      <Route path="/accept-invite/:token" element={<AcceptInvitePage />} />

      {/* Authenticated app shell */}
      <Route element={<ProtectedRoute />}>
        <Route element={<AppShell />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/customers" element={<CustomersPage />} />
          <Route path="/customers/:id" element={<CustomerDetailPage />} />
          <Route path="/jobs" element={<JobsPage />} />
          <Route path="/jobs/:id" element={<JobDetailPage />} />
          <Route path="/invoices" element={<InvoicesPage />} />
          <Route path="/invoices/:id" element={<InvoiceDetailPage />} />
          <Route path="/team" element={<TeamRoute />} />
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
