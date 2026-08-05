import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { canManageOperations, canManageUsers, useAuth } from "./context/AuthContext";
import { AcceptInvitePage } from "./pages/AcceptInvitePage";
import { ArAgingPage } from "./pages/ArAgingPage";
import { BillingSettingsPage } from "./pages/BillingSettingsPage";
import { CustomerDetailPage } from "./pages/CustomerDetailPage";
import { CustomersPage } from "./pages/CustomersPage";
import { DashboardPage } from "./pages/DashboardPage";
import { DispatchBoardPage } from "./pages/DispatchBoardPage";
import { InventoryPage } from "./pages/InventoryPage";
import { InvoiceDetailPage } from "./pages/InvoiceDetailPage";
import { InvoicesPage } from "./pages/InvoicesPage";
import { FieldPage } from "./pages/FieldPage";
import { JobDetailPage } from "./pages/JobDetailPage";
import { JobsPage } from "./pages/JobsPage";
import { LoginPage } from "./pages/LoginPage";
import { MessagesPage } from "./pages/MessagesPage";
import { PublicInvoicePage } from "./pages/PublicInvoicePage";
import { PurchaseOrdersPage } from "./pages/PurchaseOrdersPage";
import { ReportsPage } from "./pages/ReportsPage";
import { SignupPage } from "./pages/SignupPage";
import { TeamPage } from "./pages/TeamPage";
import { VendorsPage } from "./pages/VendorsPage";
import { PortalHome } from "./portal/PortalHome";
import { PortalJobs } from "./portal/PortalJobs";
import { PortalInvoices } from "./portal/PortalInvoices";
import { PortalEstimates } from "./portal/PortalEstimates";
import { PortalMessages } from "./portal/PortalMessages";

function TeamRoute() {
  const { user } = useAuth();
  // Phase 10: viewing the roster is require_operations-equivalent
  // (owner/admin/office) to match the backend's GET /users gate
  // (app/api/v1/routes/users.py) -- editing someone ELSE's profile still
  // requires admin, enforced both in TeamPage.tsx and server-side.
  if (!canManageOperations(user?.role)) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        You don't have permission to view this page. The team roster is limited to
        owners, admins, and office staff.
      </div>
    );
  }
  return <TeamPage />;
}

function BillingSettingsRoute() {
  const { user } = useAuth();
  if (!canManageUsers(user?.role)) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        You don't have permission to view this page. Billing settings are limited to
        owners and admins.
      </div>
    );
  }
  return <BillingSettingsPage />;
}

function ArAgingRoute() {
  const { user } = useAuth();
  if (!canManageOperations(user?.role)) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        You don't have permission to view this page. The AR aging report is limited to
        owners, admins, and office staff.
      </div>
    );
  }
  return <ArAgingPage />;
}

function ReportsRoute() {
  const { user } = useAuth();
  if (!canManageOperations(user?.role)) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        You don't have permission to view this page. Reports are limited to owners, admins,
        and office staff.
      </div>
    );
  }
  return <ReportsPage />;
}

function MessagesRoute() {
  const { user } = useAuth();
  if (!canManageOperations(user?.role)) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        You don't have permission to view this page. Customer messages are limited to
        owners, admins, and office staff.
      </div>
    );
  }
  return <MessagesPage />;
}

// Phase 13: inventory, vendors, and purchase orders are all
// require_operations-gated to match their backend routes
// (app/api/v1/routes/{inventory,vendors,purchase_orders}.py).
function InventoryRoute() {
  const { user } = useAuth();
  if (!canManageOperations(user?.role)) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        You don't have permission to view this page. Inventory is limited to owners,
        admins, and office staff.
      </div>
    );
  }
  return <InventoryPage />;
}

function VendorsRoute() {
  const { user } = useAuth();
  if (!canManageOperations(user?.role)) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        You don't have permission to view this page. Vendors are limited to owners,
        admins, and office staff.
      </div>
    );
  }
  return <VendorsPage />;
}

function PurchaseOrdersRoute() {
  const { user } = useAuth();
  if (!canManageOperations(user?.role)) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        You don't have permission to view this page. Purchase orders are limited to
        owners, admins, and office staff.
      </div>
    );
  }
  return <PurchaseOrdersPage />;
}

export default function App() {
  return (
    <Routes>
      {/* Unauthenticated */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
      <Route path="/pay/:token" element={<PublicInvoicePage />} />
      <Route path="/accept-invite/:token" element={<AcceptInvitePage />} />

      {/* Customer self-service portal (Phase 9) — magic-link, no staff auth.
          Deliberately isolated from the staff AppShell/nav: these pages
          render their own PortalLayout, not <AppShell />. */}
      <Route path="/portal/:token" element={<PortalHome />} />
      <Route path="/portal/:token/jobs" element={<PortalJobs />} />
      <Route path="/portal/:token/invoices" element={<PortalInvoices />} />
      <Route path="/portal/:token/estimates" element={<PortalEstimates />} />
      <Route path="/portal/:token/messages" element={<PortalMessages />} />

      {/* Phase 12: technician field app -- offline-first, single-column,
          deliberately outside <AppShell /> (no admin sidebar/nav; see
          FieldPage.tsx for why this is not a responsive reflow of the
          admin job board). Still gated by <ProtectedRoute /> since it
          needs an authenticated technician/staff session. */}
      <Route element={<ProtectedRoute />}>
        <Route path="/field" element={<FieldPage />} />
        <Route path="/field/:id" element={<FieldPage />} />
      </Route>

      {/* Authenticated app shell */}
      <Route element={<ProtectedRoute />}>
        <Route element={<AppShell />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/customers" element={<CustomersPage />} />
          <Route path="/customers/:id" element={<CustomerDetailPage />} />
          <Route path="/jobs" element={<JobsPage />} />
          <Route path="/jobs/:id" element={<JobDetailPage />} />
          <Route path="/dispatch" element={<DispatchBoardPage />} />
          <Route path="/invoices" element={<InvoicesPage />} />
          <Route path="/invoices/:id" element={<InvoiceDetailPage />} />
          <Route path="/reports/ar-aging" element={<ArAgingRoute />} />
          <Route path="/reports" element={<ReportsRoute />} />
          <Route path="/messages" element={<MessagesRoute />} />
          <Route path="/settings/billing" element={<BillingSettingsRoute />} />
          <Route path="/team" element={<TeamRoute />} />
          <Route path="/inventory" element={<InventoryRoute />} />
          <Route path="/vendors" element={<VendorsRoute />} />
          <Route path="/purchase-orders" element={<PurchaseOrdersRoute />} />
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
