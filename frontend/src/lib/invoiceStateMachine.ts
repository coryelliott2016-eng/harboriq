import type { InvoiceStatus } from "../types/api";

// Mirrors app/services/state_machines.py::InvoiceSM.transitions exactly.
// Used only to decide which action buttons the UI offers — the backend is
// the real enforcement.
export const INVOICE_STATUS_TRANSITIONS: Record<InvoiceStatus, InvoiceStatus[]> = {
  draft: ["sent", "void"],
  sent: ["partial", "paid", "void", "uncollectible"],
  partial: ["paid", "void"],
  paid: ["refunded", "partially_refunded"],
  void: [],
  uncollectible: [],
  refunded: [],
  partially_refunded: [],
};

export function canVoid(status: InvoiceStatus): boolean {
  return INVOICE_STATUS_TRANSITIONS[status]?.includes("void") ?? false;
}

export function canSend(status: InvoiceStatus): boolean {
  return status === "draft";
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
