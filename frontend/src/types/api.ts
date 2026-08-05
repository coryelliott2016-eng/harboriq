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

// Phase 10: the team roster (GET /users) and profile edit (PATCH /users/{id})
// response shape -- a superset of `User` with skills/address/coordinates.
// See app/schemas/auth.py::TeamMemberOut.
export interface TeamMember extends User {
  skills: string[];
  address_text: string | null;
  home_latitude: string | null;
  home_longitude: string | null;
}

// Every field optional (partial update). Sending `role`/`is_active` as a
// non-admin is rejected server-side with 403 -- see app/services/users.py.
export interface UserUpdateInput {
  full_name?: string | null;
  skills?: string[] | null;
  address_text?: string | null;
  role?: UserRole | null;
  is_active?: boolean | null;
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

// --- Invite-link user provisioning ---

export interface CreateInviteInput {
  email: string;
  role: UserRole;
  full_name?: string;
}

export interface InviteOut {
  email: string;
  role: UserRole;
  full_name: string | null;
  company_name: string;
  expires_in_hours: number;
  accept_url: string;
}

export interface InvitePreview {
  email: string;
  role: UserRole;
  full_name: string | null;
  company_name: string;
}

export interface AcceptInviteInput {
  password: string;
  full_name?: string;
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
  // Derived server-side by geocoding the address (Phase 10) -- null until a
  // geocode call has succeeded for this customer. See app/schemas/customers.py.
  latitude: string | null;
  longitude: string | null;
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
  required_skills: string[];
  dispatch_score: string | null;
  dispatch_score_breakdown: Record<string, string> | null;
  dispatch_scored_at: string | null;
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
  required_skills?: string[];
}

// --- AI dispatch engine (Phase 7) ---

export interface DispatchScore {
  total: string;
  breakdown: Record<string, string>;
}

export interface DispatchCandidate {
  technician_id: string;
  technician_name: string;
  score: DispatchScore;
}

export interface JobDispatchScore {
  job_id: string;
  dispatch_score: string | null;
  dispatch_score_breakdown: Record<string, string> | null;
  dispatch_scored_at: string | null;
}

// --- Phase 11: live dispatch board -- location ping + on-my-way SMS ---
// Mirrors app/schemas/dispatch_board.py exactly.

export interface LocationPingInput {
  latitude: string;
  longitude: string;
}

export interface LocationPingOut {
  id: string;
  current_latitude: string;
  current_longitude: string;
  location_updated_at: string;
}

// Best-effort position for the dispatch board map. `is_live` is true only
// when it came from an actual location-ping; false means this is a
// fallback to the technician's static home base (no ping received yet).
export interface TechnicianLocation {
  id: string;
  full_name: string | null;
  latitude: string | null;
  longitude: string | null;
  is_live: boolean;
  location_updated_at: string | null;
}

export interface OnMyWayResponse {
  outbox_event_id: number | null;
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

// --- Refunds (Phase 8) ---

export interface RefundInput {
  /** Omit for a full refund of whatever remains refundable. */
  amount?: string;
  reason?: string;
}

export interface Refund {
  id: string;
  invoice_id: string;
  amount: string;
  reason: string | null;
  stripe_refund_id: string | null;
  created_at: string;
}

export interface RefundResponse {
  invoice: Invoice;
  refund: Refund;
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

// --- Customer self-service portal (Phase 9) ---
// Mirrors app/schemas/portal.py exactly. Decimal fields are strings, same
// convention as the rest of this file.

export interface PortalVessel {
  id: string;
  name: string | null;
  make: string | null;
  model: string | null;
  year: number | null;
  hull_id: string | null;
  registration: string | null;
}

export interface PortalMe {
  id: string;
  first_name: string | null;
  last_name: string | null;
  company_name: string | null;
  email: string | null;
  phone: string | null;
  vessels: PortalVessel[];
}

export interface PortalJob {
  id: string;
  title: string | null;
  status: JobStatus;
  scheduled_at: string | null;
  scheduled_end_at: string | null;
  completed_at: string | null;
  vessel_id: string | null;
  technician_name: string | null;
}

export interface PortalInvoice {
  id: string;
  status: InvoiceStatus;
  currency: string;
  subtotal: string;
  tax_total: string;
  total: string;
  amount_paid: string;
  balance_due: string;
  due_date: string | null;
  paid_at: string | null;
  created_at: string;
}

export interface PortalEstimate {
  id: string;
  job_id: string | null;
  status: string;
  currency: string;
  subtotal: string;
  tax_total: string;
  total: string;
  approved_at: string | null;
  created_at: string;
}

export interface PortalApproveToken {
  approve_path: string;
}

export interface PortalInviteResponse {
  customer_id: string;
  outbox_event_id: number;
}

// --- Customer <-> staff messaging (Phase 9) ---
// Mirrors app/schemas/messages.py exactly.

export type MessageSenderType = "customer" | "staff";

export interface MessageCreate {
  body: string;
  job_id?: string | null;
}

export interface Message {
  id: string;
  company_id: string;
  customer_id: string;
  job_id: string | null;
  sender_type: MessageSenderType;
  sender_user_id: string | null;
  body: string;
  // 'portal' or 'sms' (migration 0010, Phase 11) -- how this message arrived.
  channel: "portal" | "sms";
  created_at: string;
  read_at: string | null;
}

export interface StaffMessageCreate extends MessageCreate {
  customer_id: string;
}

export interface InboxMessage extends Message {
  customer_label: string | null;
}

// --- Stripe Connect + dunning (Phase 8) ---
// Mirrors app/schemas/billing.py exactly.

export interface ConnectOnboardingResponse {
  account_id: string;
  onboarding_url: string;
}

export interface ConnectStatusResponse {
  connected: boolean;
  account_id: string | null;
  charges_enabled: boolean;
  details_submitted: boolean;
}

export interface DunningRunResponse {
  reminded_invoice_ids: string[];
  count: number;
}

// --- AR aging report (Phase 8) ---
// Mirrors app/schemas/reports.py exactly.

export interface AgingBuckets {
  current: string;
  days_1_30: string;
  days_31_60: string;
  days_61_90: string;
  days_90_plus: string;
}

export interface CustomerAging {
  customer_id: string | null;
  customer_name: string;
  buckets: AgingBuckets;
  total: string;
  invoice_count: number;
}

export interface ArAgingReport {
  as_of: string;
  customers: CustomerAging[];
  bucket_totals: AgingBuckets;
  grand_total: string;
}

// --- P&L and cash-flow reports (Phase 14) ---
// Mirrors app/schemas/reports.py exactly.

export interface PnlMonth {
  month: string; // "YYYY-MM"
  revenue: string;
  refunds: string;
  net_revenue: string;
  parts_cost: string;
  labor_cost: string;
  labor_cost_unavailable: boolean;
  unrated_technicians: string[];
  net: string;
}

export interface PnlTotals {
  revenue: string;
  refunds: string;
  net_revenue: string;
  parts_cost: string;
  labor_cost: string;
  labor_cost_unavailable: boolean;
  unrated_technicians: string[];
  net: string;
}

export interface PnlReport {
  start_date: string;
  end_date: string;
  months: PnlMonth[];
  totals: PnlTotals;
}

export interface CashFlowMonth {
  month: string;
  cash_in: string;
  refunds_out: string;
  cost_incurred: string;
  net_cash: string;
}

export interface CashFlowTotals {
  cash_in: string;
  refunds_out: string;
  cost_incurred: string;
  net_cash: string;
}

export interface CashFlowReport {
  start_date: string;
  end_date: string;
  months: CashFlowMonth[];
  totals: CashFlowTotals;
  cost_incurred_caveat: string;
}

// --- API error shape (see app/api/errors.py) ---
// FastAPI's default HTTPException body: {"detail": "<message>" | [...]}
export interface ApiErrorBody {
  detail?: string | { msg: string; loc?: (string | number)[] }[];
}

// --- Field app: attachments + time clock (Phase 12) ---
// Mirrors app/schemas/field_app.py exactly.

export type JobAttachmentKind = "photo" | "signature" | "other";

export interface JobAttachment {
  id: string;
  job_id: string;
  kind: JobAttachmentKind;
  content_type: string;
  uploaded_by: string;
  created_at: string;
  data: string | null;
}

export interface JobAttachmentInput {
  kind: JobAttachmentKind;
  data: string;
  content_type?: string;
  idempotency_key?: string | null;
}

export interface JobTimeEntry {
  id: string;
  job_id: string;
  technician_id: string;
  clocked_in_at: string;
  clocked_out_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ClockActionInput {
  idempotency_key?: string | null;
}

// --- inventory, vendors & purchase orders (Phase 13) ---

export interface InventoryItem {
  id: string;
  company_id: string;
  name: string;
  sku: string | null;
  unit_cost: string;
  retail_price: string;
  currency: string;
  quantity_on_hand: number;
  reorder_point: number;
  low_stock_alerted: boolean;
  default_vendor_id: string | null;
  created_at: string;
}

export interface InventoryItemInput {
  name: string;
  sku?: string | null;
  unit_cost?: string;
  retail_price?: string;
  reorder_point?: number;
  default_vendor_id?: string | null;
}

export interface ReorderSuggestion {
  id: string;
  name: string;
  sku: string | null;
  quantity_on_hand: number;
  reorder_point: number;
  default_vendor_id: string | null;
  unit_cost: string;
}

export interface GeneratePOInput {
  vendor_id: string;
  item_ids: string[];
}

export interface Vendor {
  id: string;
  company_id: string;
  name: string;
  contact_email: string | null;
  contact_phone: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface VendorInput {
  name: string;
  contact_email?: string | null;
  contact_phone?: string | null;
  notes?: string | null;
}

export type PurchaseOrderStatus = "draft" | "submitted" | "received" | "cancelled";

export interface PurchaseOrderLineItem {
  id: string;
  inventory_item_id: string;
  quantity_ordered: number;
  quantity_received: number;
  unit_cost: string;
}

export interface PurchaseOrderLineItemInput {
  inventory_item_id: string;
  quantity_ordered: number;
  unit_cost?: string;
}

export interface PurchaseOrder {
  id: string;
  company_id: string;
  vendor_id: string;
  status: PurchaseOrderStatus;
  created_by: string;
  submitted_at: string | null;
  received_at: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  line_items: PurchaseOrderLineItem[];
}

export interface PurchaseOrderInput {
  vendor_id: string;
  notes?: string | null;
  line_items: PurchaseOrderLineItemInput[];
}

export interface ReceiptLineInput {
  line_item_id: string;
  quantity: number;
}

export interface ReceivePurchaseOrderInput {
  receipts: ReceiptLineInput[];
}
