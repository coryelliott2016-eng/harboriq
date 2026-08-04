import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DispatchBreakdown } from "./DispatchBreakdown";

describe("DispatchBreakdown", () => {
  it("renders the total score and every breakdown factor", () => {
    render(
      <DispatchBreakdown
        score={{
          total: "42.50",
          breakdown: { urgency: "17.50", revenue: "10.00", technician_fit: "15.00" },
        }}
      />,
    );

    expect(screen.getByText(/Score 42.50/)).toBeInTheDocument();
    expect(screen.getByText("Urgency")).toBeInTheDocument();
    expect(screen.getByText("Skill fit")).toBeInTheDocument();
  });

  it("renders negative factors (e.g. workload) distinctly", () => {
    render(
      <DispatchBreakdown
        score={{ total: "12.00", breakdown: { urgency: "18.00", workload: "-6.00" } }}
      />,
    );

    expect(screen.getByText("Workload")).toBeInTheDocument();
    expect(screen.getByText("-6.00")).toBeInTheDocument();
  });
});
