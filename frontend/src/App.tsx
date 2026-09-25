import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { canManageOperations, canManageUsers, useAuth } from "./context/auth";

// Phase 22 (bundle-size P2): every route-level page is code-split via
// React.lazy so the initial bundle only ships the app shell + router, not
// every page in the product. Each page module still uses a NAMED export
// (unchanged, so nothing else importing these pages has to change) --
// `.then((m) => ({ default: m.X }))` adapts the named export to the default
// export React.lazy() requires. AppShell/ProtectedRoute stay eager: they
// wrap almost every authenticated route, so lazy-loading them would just
// add a second waterfall for no bundle-size win.
const AcceptInvitePage = lazy(() =>
  import("./pages/AcceptInvitePage").then((m) => ({
    default: m.AcceptInvitePage,
  })),
);
const ArAgingPage = lazy(() =>
  import("./pages/ArAgingPage").then((m) => ({ default: m.ArAgingPage })),
);
const BillingSettingsPage = lazy(() =>
  import("./pages/BillingSettingsPage").then((m) => ({
    default: m.BillingSettingsPage,
  })),
);
const CustomerDetailPage = lazy(() =>
  import("./pages/CustomerDetailPage").then((m) => ({
    default: m.CustomerDetailPage,
  })),
);
const CustomersPage = lazy(() =>
  import("./pages/CustomersPage").then((m) => ({ default: m.CustomersPage })),
);
const DashboardPage = lazy(() =>
  import("./pages/DashboardPage").then((m) => ({ default: m.DashboardPage })),
);
const DispatchBoardPage = lazy(() =>
  import("./pages/DispatchBoardPage").then((m) => ({
    default: m.DispatchBoardPage,
  })),
);
const InventoryPage = lazy(() =>
  import("./pages/InventoryPage").then((m) => ({ default: m.InventoryPage })),
);
const InvoiceDetailPage = lazy(() =>
  import("./pages/InvoiceDetailPage").then((m) => ({
    default: m.InvoiceDetailPage,
  })),
);
const InvoicesPage = lazy(() =>
  import("./pages/InvoicesPage").then((m) => ({ default: m.InvoicesPage })),
);
const FieldPage = lazy(() =>
  import("./pages/FieldPage").then((m) => ({ default: m.FieldPage })),
);
const JobDetailPage = lazy(() =>
  import("./pages/JobDetailPage").then((m) => ({ default: m.JobDetailPage })),
);
const JobsPage = lazy(() =>
  import("./pages/JobsPage").then((m) => ({ default: m.JobsPage })),
);
const LoginPage = lazy(() =>
  import("./pages/LoginPage").then((m) => ({ default: m.LoginPage })),
);
const MessagesPage = lazy(() =>
  import("./pages/MessagesPage").then((m) => ({ default: m.MessagesPage })),
);
const PublicInvoicePage = lazy(() =>
  import("./pages/PublicInvoicePage").then((m) => ({
    default: m.PublicInvoicePage,
  })),
);
const PurchaseOrdersPage = lazy(() =>
  import("./pages/PurchaseOrdersPage").then((m) => ({
    default: m.PurchaseOrdersPage,
  })),
);
const ReportsPage = lazy(() =>
  import("./pages/ReportsPage").then((m) => ({ default: m.ReportsPage })),
);
const SecuritySettingsPage = lazy(() =>
  import("./pages/SecuritySettingsPage").then((m) => ({
    default: m.SecuritySettingsPage,
  })),
);
const SignupPage = lazy(() =>
  import("./pages/SignupPage").then((m) => ({ default: m.SignupPage })),
);
const SlipMapPage = lazy(() =>
  import("./pages/SlipMapPage").then((m) => ({ default: m.SlipMapPage })),
);
const SlipReservationsPage = lazy(() =>
  import("./pages/SlipReservationsPage").then((m) => ({
    default: m.SlipReservationsPage,
  })),
);
const SlipsPage = lazy(() =>
  import("./pages/SlipsPage").then((m) => ({ default: m.SlipsPage })),
);
const TeamPage = lazy(() =>
  import("./pages/TeamPage").then((m) => ({ default: m.TeamPage })),
);
const VendorsPage = lazy(() =>
  import("./pages/VendorsPage").then((m) => ({ default: m.VendorsPage })),
);
const PortalHome = lazy(() =>
  import("./portal/PortalHome").then((m) => ({ default: m.PortalHome })),
);
const PortalJobs = lazy(() =>
  import("./portal/PortalJobs").then((m) => ({ default: m.PortalJobs })),
);
const PortalInvoices = lazy(() =>
  import("./portal/PortalInvoices").then((m) => ({
    default: m.PortalInvoices,
  })),
);
const PortalEstimates = lazy(() =>
  import("./portal/PortalEstimates").then((m) => ({
    default: m.PortalEstimates,
  })),
);
const PortalMessages = lazy(() =>
  import("./portal/PortalMessages").then((m) => ({
    default: m.PortalMessages,
  })),
);
const PortalDockLocation = lazy(() =>
  import("./portal/PortalDockLocation").then((m) => ({
    default: m.PortalDockLocation,
  })),
);

// Full-viewport, minimal fallback shown while a lazy route chunk loads.
// Deliberately plain (no layout dependency) since it can render before
// AppShell/PortalLayout/FieldPage's own chrome has loaded.
function RouteFallback() {
  return (
    <div className="flex min-h-[50vh] items-center justify-center text-sm text-slate-500">
      Loading…
    </div>
  );
}

function TeamRoute() {
  const { user } = useAuth();
  // Phase 10: viewing the roster is require_operations-equivalent
  // (owner/admin/office) to match the backend's GET /users gate
  // (app/api/v1/routes/users.py) -- editing someone ELSE's profile still
  // requires admin, enforced both in TeamPage.tsx and server-side.
  if (!canManageOperations(user?.role)) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        You don't have permission to view this page. The team roster is limited
        to owners, admins, and office staff.
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
        You don't have permission to view this page. Billing settings are
        limited to owners and admins.
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
        You don't have permission to view this page. The AR aging report is
        limited to owners, admins, and office staff.
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
        You don't have permission to view this page. Reports are limited to
        owners, admins, and office staff.
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
        You don't have permission to view this page. Customer messages are
        limited to owners, admins, and office staff.
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
        You don't have permission to view this page. Inventory is limited to
        owners, admins, and office staff.
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
        You don't have permission to view this page. Vendors are limited to
        owners, admins, and office staff.
      </div>
    );
  }
  return <VendorsPage />;
}

// Phase 15: marina/slip management is require_operations-gated to match
// its backend routes (app/api/v1/routes/{slips,slip_reservations}.py).
function SlipMapRoute() {
  const { user } = useAuth();
  if (!canManageOperations(user?.role)) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        You don't have permission to view this page. The slip map is limited to
        owners, admins, and office staff.
      </div>
    );
  }
  return <SlipMapPage />;
}

function SlipsRoute() {
  const { user } = useAuth();
  if (!canManageOperations(user?.role)) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        You don't have permission to view this page. Slip management is limited
        to owners, admins, and office staff.
      </div>
    );
  }
  return <SlipsPage />;
}

function SlipReservationsRoute() {
  const { user } = useAuth();
  if (!canManageOperations(user?.role)) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        You don't have permission to view this page. Slip reservations are
        limited to owners, admins, and office staff.
      </div>
    );
  }
  return <SlipReservationsPage />;
}

function PurchaseOrdersRoute() {
  const { user } = useAuth();
  if (!canManageOperations(user?.role)) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        You don't have permission to view this page. Purchase orders are limited
        to owners, admins, and office staff.
      </div>
    );
  }
  return <PurchaseOrdersPage />;
}

export default function App() {
  return (
    <Suspense fallback={<RouteFallback />}>
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
        <Route path="/portal/:token/dock" element={<PortalDockLocation />} />

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
            <Route
              path="/settings/billing"
              element={<BillingSettingsRoute />}
            />
            <Route
              path="/settings/security"
              element={<SecuritySettingsPage />}
            />
            <Route path="/team" element={<TeamRoute />} />
            <Route path="/inventory" element={<InventoryRoute />} />
            <Route path="/vendors" element={<VendorsRoute />} />
            <Route path="/purchase-orders" element={<PurchaseOrdersRoute />} />
            <Route path="/marina/slip-map" element={<SlipMapRoute />} />
            <Route path="/marina/slips" element={<SlipsRoute />} />
            <Route
              path="/marina/reservations"
              element={<SlipReservationsRoute />}
            />
          </Route>
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
