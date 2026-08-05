import { api, apiRequest, downloadFile } from "./api";
import type {
  AcceptInviteInput,
  ArAgingReport,
  AuthResponse,
  CashFlowReport,
  PnlReport,
  ConnectOnboardingResponse,
  ConnectStatusResponse,
  CreateInviteInput,
  Customer,
  CustomerInput,
  DispatchCandidate,
  DunningRunResponse,
  GeneratePOInput,
  InventoryItem,
  InventoryItemInput,
  Invoice,
  InvoiceDetail,
  InvoiceSendResponse,
  InboxMessage,
  InviteOut,
  InvitePreview,
  ClockActionInput,
  Job,
  JobAttachment,
  JobAttachmentInput,
  JobDetail,
  JobDispatchScore,
  JobInput,
  JobLineItem,
  JobLineItemInput,
  JobStatus,
  JobTimeEntry,
  LocationPingInput,
  LocationPingOut,
  Message,
  MessageCreate,
  OnMyWayResponse,
  PortalApproveToken,
  PortalEstimate,
  PortalInvoice,
  PortalInviteResponse,
  PortalJob,
  PortalMe,
  PublicInvoice,
  PurchaseOrder,
  PurchaseOrderInput,
  ReceivePurchaseOrderInput,
  RefundInput,
  RefundResponse,
  ReorderSuggestion,
  StaffMessageCreate,
  TeamMember,
  TechnicianLocation,
  User,
  UserRole,
  UserUpdateInput,
  Vendor,
  VendorInput,
  Vessel,
  VesselInput,
  VoidInvoiceResponse,
} from "../types/api";

// --- auth ---

export const authApi = {
  signup: (body: {
    company_name: string;
    email: string;
    password: string;
    full_name?: string;
  }) => apiRequest<AuthResponse>("/auth/signup", { method: "POST", body, anonymous: true }),

  login: (body: { email: string; password: string }) =>
    apiRequest<AuthResponse>("/auth/login", { method: "POST", body, anonymous: true }),

  me: () => api.get<User>("/auth/me"),

  logout: (allDevices = false) =>
    api.post<{ revoked_sessions: number }>("/auth/logout", { all_devices: allDevices }),

  createUser: (body: {
    email: string;
    password: string;
    role: UserRole;
    full_name?: string;
  }) => api.post<User>("/auth/users", body),

  createInvite: (body: CreateInviteInput) => api.post<InviteOut>("/auth/invites", body),

  getInvite: (token: string) =>
    apiRequest<InvitePreview>(`/auth/invites/${token}`, { anonymous: true }),

  acceptInvite: (token: string, body: AcceptInviteInput) =>
    apiRequest<AuthResponse>(`/auth/invites/${token}/accept`, {
      method: "POST",
      body,
      anonymous: true,
    }),
};

// --- team roster + self-service/admin profile editing (Phase 10) ---

export const usersApi = {
  list: () => api.get<TeamMember[]>("/users"),
  update: (id: string, body: UserUpdateInput) => api.patch<TeamMember>(`/users/${id}`, body),
  // Phase 11 live dispatch board.
  pingLocation: (body: LocationPingInput) =>
    api.post<LocationPingOut>("/users/me/location-ping", body),
  technicianLocations: () => api.get<TechnicianLocation[]>("/users/technician-locations"),
};

// --- customers ---

export const customersApi = {
  list: (search?: string) => api.get<Customer[]>("/customers", { search }),
  get: (id: string) => api.get<Customer>(`/customers/${id}`),
  create: (body: CustomerInput) => api.post<Customer>("/customers", body),
  update: (id: string, body: Partial<CustomerInput>) =>
    api.patch<Customer>(`/customers/${id}`, body),
  remove: (id: string) => api.delete<void>(`/customers/${id}`),
  vessels: (id: string) => api.get<Vessel[]>(`/customers/${id}/vessels`),
  sendPortalInvite: (id: string) =>
    api.post<PortalInviteResponse>(`/customers/${id}/portal-invite`, {}),
};

// --- vessels ---

export const vesselsApi = {
  list: (customerId?: string) => api.get<Vessel[]>("/vessels", { customer_id: customerId }),
  get: (id: string) => api.get<Vessel>(`/vessels/${id}`),
  create: (body: VesselInput) => api.post<Vessel>("/vessels", body),
  update: (id: string, body: Partial<VesselInput>) =>
    api.patch<Vessel>(`/vessels/${id}`, body),
  remove: (id: string) => api.delete<void>(`/vessels/${id}`),
};

// --- jobs ---

export const jobsApi = {
  list: (params?: {
    status?: JobStatus;
    customer_id?: string;
    vessel_id?: string;
    sort?: "scheduled_at" | "priority_score";
  }) => api.get<Job[]>("/jobs", params),
  get: (id: string) => api.get<JobDetail>(`/jobs/${id}`),
  create: (body: JobInput) => api.post<Job>("/jobs", body),
  update: (id: string, body: Partial<JobInput>) => api.patch<Job>(`/jobs/${id}`, body),
  remove: (id: string) => api.delete<void>(`/jobs/${id}`),
  assign: (id: string, technicianId: string | null) =>
    api.post<Job>(`/jobs/${id}/assign`, { technician_id: technicianId }),
  setStatus: (id: string, targetStatus: JobStatus, holdReason?: string) =>
    api.post<Job>(`/jobs/${id}/status`, { status: targetStatus, hold_reason: holdReason }),
  lineItems: (id: string) => api.get<JobLineItem[]>(`/jobs/${id}/line-items`),
  addLineItem: (id: string, body: JobLineItemInput) =>
    api.post<JobLineItem>(`/jobs/${id}/line-items`, body),
  updateLineItem: (jobId: string, lineItemId: string, body: Partial<JobLineItemInput>) =>
    api.patch<JobLineItem>(`/jobs/${jobId}/line-items/${lineItemId}`, body),
  removeLineItem: (jobId: string, lineItemId: string) =>
    api.delete<void>(`/jobs/${jobId}/line-items/${lineItemId}`),
  notifyOnMyWay: (id: string) =>
    api.post<OnMyWayResponse>(`/jobs/${id}/notify-on-my-way`, {}),
};

// --- AI dispatch engine (Phase 7) ---

export const dispatchApi = {
  candidates: (jobId: string) =>
    api.get<DispatchCandidate[]>(`/jobs/${jobId}/dispatch/candidates`),
  recompute: (jobId: string) =>
    api.post<JobDispatchScore>(`/jobs/${jobId}/dispatch/recompute`, {}),
};

// --- invoices ---

export const invoicesApi = {
  list: (params?: { status?: string; customer_id?: string; job_id?: string }) =>
    api.get<Invoice[]>("/invoices", params),
  get: (id: string) => api.get<InvoiceDetail>(`/invoices/${id}`),
  createFromJob: (jobId: string, taxRate?: string) =>
    api.post<InvoiceDetail>("/invoices", { job_id: jobId, tax_rate: taxRate ?? "0" }),
  send: (id: string) => api.post<InvoiceSendResponse>(`/invoices/${id}/send`),
  void: (id: string) => api.post<VoidInvoiceResponse>(`/invoices/${id}/void`),
  refund: (id: string, body: RefundInput = {}) =>
    api.post<RefundResponse>(`/invoices/${id}/refund`, body),
};

// --- billing admin (Stripe Connect + dunning; owner/admin only) ---

export const billingApi = {
  connectOnboardingLink: () =>
    api.post<ConnectOnboardingResponse>("/billing/connect/onboarding-link", {}),
  connectStatus: () => api.get<ConnectStatusResponse>("/billing/connect/status"),
  runDunning: () => api.post<DunningRunResponse>("/billing/dunning/run", {}),
};

// --- reports (owner/admin/office) ---

export interface ReportDateRange {
  start_date?: string;
  end_date?: string;
  [key: string]: string | number | boolean | undefined | null;
}

export const reportsApi = {
  arAging: () => api.get<ArAgingReport>("/reports/ar-aging"),
  pnl: (range?: ReportDateRange) => api.get<PnlReport>("/reports/pnl", range),
  cashFlow: (range?: ReportDateRange) => api.get<CashFlowReport>("/reports/cash-flow", range),

  // CSV / QuickBooks Online-style export downloads (Phase 14). Each
  // triggers a browser file download rather than returning parsed data --
  // see `downloadFile` in lib/api.ts for why these can't go through the
  // normal JSON-only `api.get`.
  exportArAgingCsv: () => downloadFile("/reports/ar-aging/export.csv", undefined, "ar_aging.csv"),
  exportPnlCsv: (range?: ReportDateRange) =>
    downloadFile("/reports/pnl/export.csv", range, "pnl.csv"),
  exportCashFlowCsv: (range?: ReportDateRange) =>
    downloadFile("/reports/cash-flow/export.csv", range, "cash_flow.csv"),
  exportTransactionsCsv: (range?: ReportDateRange) =>
    downloadFile("/reports/transactions/export.csv", range, "transactions_qbo.csv"),
};

// --- public (unauthenticated) ---

export const publicApi = {
  getInvoice: (token: string) =>
    apiRequest<PublicInvoice>(`/public/invoice/${token}`, { anonymous: true }),
};

// --- customer self-service portal (Phase 9, unauthenticated + magic link) ---

export const portalApi = {
  me: (token: string) => apiRequest<PortalMe>(`/portal/${token}/me`, { anonymous: true }),
  jobs: (token: string) =>
    apiRequest<PortalJob[]>(`/portal/${token}/jobs`, { anonymous: true }),
  invoices: (token: string) =>
    apiRequest<PortalInvoice[]>(`/portal/${token}/invoices`, { anonymous: true }),
  invoicePayUrl: (token: string, invoiceId: string) =>
    apiRequest<{ checkout_url: string | null }>(
      `/portal/${token}/invoices/${invoiceId}/pay-url`,
      { anonymous: true },
    ),
  estimates: (token: string) =>
    apiRequest<PortalEstimate[]>(`/portal/${token}/estimates`, { anonymous: true }),
  estimateApproveToken: (token: string, estimateId: string) =>
    apiRequest<PortalApproveToken>(
      `/portal/${token}/estimates/${estimateId}/approve-token`,
      { method: "POST", anonymous: true },
    ),
  messages: (token: string) =>
    apiRequest<Message[]>(`/portal/${token}/messages`, { anonymous: true }),
  sendMessage: (token: string, body: MessageCreate) =>
    apiRequest<Message>(`/portal/${token}/messages`, {
      method: "POST",
      body,
      anonymous: true,
    }),
};

// --- staff-side customer messaging (Phase 9) ---

export const messagesApi = {
  inbox: (unreadOnly = false) =>
    api.get<InboxMessage[]>("/messages", { unread_only: unreadOnly }),
  reply: (body: StaffMessageCreate) => api.post<Message>("/messages", body),
  markRead: (id: string) => api.post<Message>(`/messages/${id}/read`, {}),
  byJob: (jobId: string) => api.get<Message[]>(`/messages/by-job/${jobId}`),
};

// --- field app: attachments + time clock (Phase 12) ---

export const fieldApi = {
  attachments: (jobId: string) => api.get<JobAttachment[]>(`/jobs/${jobId}/attachments`),
  addAttachment: (jobId: string, body: JobAttachmentInput) =>
    api.post<JobAttachment>(`/jobs/${jobId}/attachments`, body),
  clockIn: (jobId: string, body: ClockActionInput = {}) =>
    api.post<JobTimeEntry>(`/jobs/${jobId}/clock-in`, body),
  clockOut: (jobId: string, body: ClockActionInput = {}) =>
    api.post<JobTimeEntry>(`/jobs/${jobId}/clock-out`, body),
  timeEntries: (jobId: string) => api.get<JobTimeEntry[]>(`/jobs/${jobId}/time-entries`),
};

// --- inventory, vendors & purchase orders (Phase 13) ---

export const inventoryApi = {
  list: (params?: { search?: string; low_stock_only?: boolean; limit?: number; offset?: number }) =>
    api.get<InventoryItem[]>("/inventory", params),
  get: (id: string) => api.get<InventoryItem>(`/inventory/${id}`),
  lookupBySku: (sku: string) => api.get<InventoryItem>("/inventory/lookup", { sku }),
  create: (body: InventoryItemInput) => api.post<InventoryItem>("/inventory", body),
  update: (id: string, body: Partial<InventoryItemInput>) =>
    api.patch<InventoryItem>(`/inventory/${id}`, body),
  reorderSuggestions: () => api.get<ReorderSuggestion[]>("/inventory/reorder-suggestions"),
  generatePurchaseOrder: (body: GeneratePOInput) =>
    api.post<PurchaseOrder>("/inventory/reorder-suggestions/generate-po", body),
};

export const vendorsApi = {
  list: (search?: string) => api.get<Vendor[]>("/vendors", { search }),
  get: (id: string) => api.get<Vendor>(`/vendors/${id}`),
  create: (body: VendorInput) => api.post<Vendor>("/vendors", body),
  update: (id: string, body: Partial<VendorInput>) => api.patch<Vendor>(`/vendors/${id}`, body),
};

export const purchaseOrdersApi = {
  list: (status?: string) => api.get<PurchaseOrder[]>("/purchase-orders", { status }),
  get: (id: string) => api.get<PurchaseOrder>(`/purchase-orders/${id}`),
  create: (body: PurchaseOrderInput) => api.post<PurchaseOrder>("/purchase-orders", body),
  submit: (id: string) => api.post<PurchaseOrder>(`/purchase-orders/${id}/submit`, {}),
  receive: (id: string, body: ReceivePurchaseOrderInput) =>
    api.post<PurchaseOrder>(`/purchase-orders/${id}/receive`, body),
  cancel: (id: string) => api.post<PurchaseOrder>(`/purchase-orders/${id}/cancel`, {}),
};
