import { api, apiRequest } from "./api";
import type {
  AcceptInviteInput,
  AuthResponse,
  CreateInviteInput,
  Customer,
  CustomerInput,
  Invoice,
  InvoiceDetail,
  InvoiceSendResponse,
  InviteOut,
  InvitePreview,
  Job,
  JobDetail,
  JobInput,
  JobLineItem,
  JobLineItemInput,
  JobStatus,
  PublicInvoice,
  User,
  UserRole,
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

// --- customers ---

export const customersApi = {
  list: (search?: string) => api.get<Customer[]>("/customers", { search }),
  get: (id: string) => api.get<Customer>(`/customers/${id}`),
  create: (body: CustomerInput) => api.post<Customer>("/customers", body),
  update: (id: string, body: Partial<CustomerInput>) =>
    api.patch<Customer>(`/customers/${id}`, body),
  remove: (id: string) => api.delete<void>(`/customers/${id}`),
  vessels: (id: string) => api.get<Vessel[]>(`/customers/${id}/vessels`),
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
  list: (params?: { status?: JobStatus; customer_id?: string; vessel_id?: string }) =>
    api.get<Job[]>("/jobs", params),
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
};

// --- public (unauthenticated) ---

export const publicApi = {
  getInvoice: (token: string) =>
    apiRequest<PublicInvoice>(`/public/invoice/${token}`, { anonymous: true }),
};
