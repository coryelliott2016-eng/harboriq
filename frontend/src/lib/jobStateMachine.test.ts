import { describe, expect, it } from "vitest";
import { canTransition, legalNextStatuses } from "./jobStateMachine";

// Mirrors app/services/state_machines.py::JobSM.transitions exactly:
//   scheduled -> {in_progress, canceled}
//   in_progress -> {on_hold, completed, canceled}
//   on_hold -> {in_progress, canceled}
//   completed -> {} (terminal)
//   canceled -> {} (terminal)
describe("job status-transition gating", () => {
  it("allows the legal transitions out of scheduled", () => {
    expect(legalNextStatuses("scheduled").sort()).toEqual(["canceled", "in_progress"]);
    expect(canTransition("scheduled", "in_progress")).toBe(true);
    expect(canTransition("scheduled", "canceled")).toBe(true);
  });

  it("rejects an illegal transition out of scheduled", () => {
    expect(canTransition("scheduled", "completed")).toBe(false);
    expect(canTransition("scheduled", "on_hold")).toBe(false);
  });

  it("allows the legal transitions out of in_progress", () => {
    expect(legalNextStatuses("in_progress").sort()).toEqual(["canceled", "completed", "on_hold"]);
  });

  it("allows resuming from on_hold back to in_progress, or canceling", () => {
    expect(canTransition("on_hold", "in_progress")).toBe(true);
    expect(canTransition("on_hold", "canceled")).toBe(true);
    expect(canTransition("on_hold", "completed")).toBe(false);
  });

  it("treats completed and canceled as terminal", () => {
    expect(legalNextStatuses("completed")).toEqual([]);
    expect(legalNextStatuses("canceled")).toEqual([]);
    expect(canTransition("completed", "in_progress")).toBe(false);
    expect(canTransition("canceled", "scheduled")).toBe(false);
  });
});
