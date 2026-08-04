import type { InvoiceStatus } from "../types/api";

// Mirrors app/services/state_machines.py::InvoiceSM.transitions exactly.
// Used only to decide which action buttons the UI offers — the backend is
// the real enforcement.
export const INVOICE_STATUS_TRANSITIONS: Record<InvoiceStatus, InvoiceStatus[]> = {
  draft: ["sent", "void"],
  sent: ["partial", "paid", "void", "uncollectible"],
  // Phase 8: a deposit ("partial") can be refunded before the balance is
  // ever paid in full -- see app/services/state_machines.py::InvoiceSM.
  partial: ["paid", "void", "partially_refunded"],
  paid: ["refunded", "partially_refunded"],
  void: [],
  uncollectible: [],
  refunded: [],
  // A partial refund can be topped up by another partial refund, or
  // completed by refunding the remainder ("refunded").
  partially_refunded: ["refunded", "partially_refunded"],
};

export function canVoid(status: InvoiceStatus): boolean {
  return INVOICE_STATUS_TRANSITIONS[status]?.includes("void") ?? false;
}

export function canSend(status: InvoiceStatus): boolean {
  return status === "draft";
}

// Mirrors the backend's refundable statuses (anything with money collected
// that hasn't already been fully refunded): `partial`, `paid`, and
// `partially_refunded` (a partial refund can be topped up further).
export function canRefund(status: InvoiceStatus): boolean {
  return status === "partial" || status === "paid" || status === "partially_refunded";
}

export const INVOICE_STATUS_LABELS: Record<InvoiceStatus, string> = {
  draft: "Draft",
  sent: "Sent",
  partial: "Partially paid",
  paid: "Paid",
  void: "Void",
  uncollectible: "Uncollectible",
  refunded: "Refunded",
  partially_refunded: "Partially refunded",
};
