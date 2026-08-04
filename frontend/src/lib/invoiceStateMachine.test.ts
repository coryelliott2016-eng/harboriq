import { describe, expect, it } from "vitest";
import { canSend, canVoid } from "./invoiceStateMachine";

// Mirrors app/services/state_machines.py::InvoiceSM.transitions:
//   draft -> {sent, void}
//   sent -> {partial, paid, void, uncollectible}
//   partial -> {paid, void}
//   paid -> {refunded, partially_refunded}   (no void)
//   void / uncollectible / refunded / partially_refunded -> {} (terminal)
describe("invoice void-button visibility", () => {
  it("shows void for draft (the invoice never left the shop)", () => {
    expect(canVoid("draft")).toBe(true);
  });

  it("shows void for sent (nothing collected yet)", () => {
    expect(canVoid("sent")).toBe(true);
  });

  it("shows void for partial (some but not all collected)", () => {
    expect(canVoid("partial")).toBe(true);
  });

  it("hides void once paid — refunds are a different flow", () => {
    expect(canVoid("paid")).toBe(false);
  });

  it("hides void for already-terminal statuses", () => {
    expect(canVoid("void")).toBe(false);
    expect(canVoid("uncollectible")).toBe(false);
    expect(canVoid("refunded")).toBe(false);
    expect(canVoid("partially_refunded")).toBe(false);
  });
});

describe("invoice send-button visibility", () => {
  it("only offers send while the invoice is still a draft", () => {
    expect(canSend("draft")).toBe(true);
    expect(canSend("sent")).toBe(false);
    expect(canSend("paid")).toBe(false);
    expect(canSend("void")).toBe(false);
  });
});
