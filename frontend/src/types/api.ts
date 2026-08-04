// Types mirror app/schemas/*.py and app/db/models.py enums. Decimal fields
// come over the wire as JSON strings (Pydantic's default Decimal encoding),
// so they are typed `string` here, not `number`.

export type UserRole = "owner" | "admin" | "office" | "technician";

export interface User {
  id: string;
  company_id: string;
  email: string;
  full_name: string | null;
  role: UserRole;
  is_active: boolean;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface AuthResponse {
  user: User;
  tokens: TokenPair;
}

// --- Customers ---

export interface Customer {
  id: string;
  company_id: string;
  first_name: string | null;
  last_name: string | null;
  company_name: string | null;
  email: string | null;
  phone: string | null;
  address_line1: string | null;
  address_line2: string | null;
  city: string | null;
  state: string | null;
  postal_code: string | null;
  country: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface CustomerInput {
  first_name?: string | null;
  last_name?: string | null;
  company_name?: string | null;
  email?: string | null;
  phone?: string | null;
  address_line1?: string | null;
  address_line2?: string | null;
  city?: string | null;
  state?: string | null;
  postal_code?: string | null;
  country?: string | null;
  notes?: string | null;
}

// --- Vessels ---

export interface Vessel {
  id: string;
  company_id: string;
  customer_id: string;
  name: string | null;
  make: string | null;
  model: string | null;
  year: number | null;
  hull_id: string | null;
  registration: string | null;
  length_ft: string | null;
  beam_ft: string | null;
  draft_ft: string | null;
  engine_make: string | null;
  engine_model: string | null;
  engine_hours: number | null;
  engine_count: number;
  storage_location: string | null;
  slip_number: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface VesselInput {
  customer_id: string;
  name?: string | null;
  make?: string | null;
  model?: string | null;
  year?: number | null;
  hull_id?: string | null;
  registration?: string | null;
  length_ft?: number | null;
  beam_ft?: number | null;
  draft_ft?: number | null;
  engine_make?: string | null;
  engine_model?: string | null;
  engine_hours?: number | null;
  engine_count?: number | null;
  storage_location?: string | null;
  slip_number?: string | null;
  notes?: string | null;
}

// --- Jobs ---

export type JobStatus =
  | "scheduled"
  | "in_progress"
  | "on_hold"
  | "completed"
  | "canceled";

export type JobPriority = "low" | "normal" | "high" | "urgent";

export type JobLineItemKind = "labor" | "part" | "fee";

export interface Job {
  id: string;
  company_id: string;
  customer_id: string;
  vessel_id: string | null;
  title: string;
  description: string | null;
  status: JobStatus;
  priority: JobPriority;
  scheduled_at: string | null;
  scheduled_end_at: string | null;
  technician_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  canceled_at: string | null;
  hold_reason: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface JobLineItem {
  id: string;
  job_id: string;
  kind: JobLineItemKind;
  description: string;
  inventory_item_id: string | null;
  quantity: string;
  unit_price: string;
  line_total: string;
  taxable: boolean;
  inventory_committed: boolean;
  invoice_id: string | null;
  invoiced_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface JobDetail extends Job {
  line_items: JobLineItem[];
}

export interface JobInput {
  customer_id: string;
  vessel_id?: string | null;
  title: string;
  description?: string | null;
  priority?: JobPriority;
  scheduled_at?: string | null;
  scheduled_end_at?: string | null;
  technician_id?: string | null;
  notes?: string | null;
}

export interface JobLineItemInput {
  kind: JobLineItemKind;
  description: string;
  quantity: string;
  unit_price: string;
  taxable: boolean;
  inventory_item_id?: string | null;
}

// The legal next-states for each job status, mirroring
// app/services/state_machines.py::JobSM exactly. Kept as a single source of
// truth in one file (see src/lib/jobStateMachine.ts) — this type just names
// the shape.
export type JobStatusTransitions = Record<JobStatus, JobStatus[]>;

// --- Invoices ---

export type InvoiceStatus =
  | "draft"
  | "sent"
  | "partial"
  | "paid"
  | "void"
  | "uncollectible"
  | "refunded"
  | "partially_refunded";

export interface InvoiceLineItem {
  id: string;
  job_id: string;
  kind: JobLineItemKind;
  description: string;
  quantity: string;
  unit_price: string;
  line_total: string;
  taxable: boolean;
  invoiced_at: string | null;
}

export interface Invoice {
  id: string;
  company_id: string;
  estimate_id: string | null;
  customer_id: string | null;
  status: InvoiceStatus;
  currency: string;
  subtotal: string;
  tax_total: string;
  tax_rate: string;
  total: string;
  amount_paid: string;
  balance_due: string;
  due_date: string | null;
  sent_at: string | null;
  paid_at: string | null;
  voided_at: string | null;
  stripe_payment_intent_id: string | null;
  stripe_checkout_session_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface InvoiceDetail extends Invoice {
  line_items: InvoiceLineItem[];
}

export interface InvoiceSendResponse {
  invoice: Invoice;
  pay_token: string;
  pay_url: string;
}

export interface VoidInvoiceResponse {
  invoice: Invoice;
}

// --- Public pay page ---

export interface PublicInvoice {
  id: string;
  status: InvoiceStatus;
  currency: string;
  subtotal: string;
  tax_total: string;
  total: string;
  amount_paid: string;
  balance_due: string;
  due_date: string | null;
  line_items: InvoiceLineItem[];
  checkout_url: string | null;
}

// --- API error shape (see app/api/errors.py) ---
// FastAPI's default HTTPException body: {"detail": "<message>" | [...]}
export interface ApiErrorBody {
  detail?: string | { msg: string; loc?: (string | number)[] }[];
}
