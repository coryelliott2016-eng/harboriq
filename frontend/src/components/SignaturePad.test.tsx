import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SignaturePad } from "./SignaturePad";

/**
 * jsdom's HTMLCanvasElement has no real 2D rendering context, so we stub
 * getContext/toDataURL to observe the drawing calls the component makes and
 * to make Save export a deterministic value -- the interesting behavior to
 * test here is the component's pointer-event wiring and button
 * enable/disable state, not actual pixel output.
 */
function stubCanvasContext() {
  const ctx = {
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
    clearRect: vi.fn(),
    lineWidth: 0,
    lineCap: "round",
    strokeStyle: "",
  };
  HTMLCanvasElement.prototype.getContext = vi.fn(() => ctx) as unknown as typeof HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.toDataURL = vi.fn(() => "data:image/png;base64,FAKESIGNATUREDATA");
  HTMLCanvasElement.prototype.getBoundingClientRect = vi.fn(() => ({
    left: 0,
    top: 0,
    width: 600,
    height: 220,
    right: 600,
    bottom: 220,
    x: 0,
    y: 0,
    toJSON: () => {},
  }));
  if (!HTMLCanvasElement.prototype.setPointerCapture) {
    HTMLCanvasElement.prototype.setPointerCapture = vi.fn();
  }
  return ctx;
}

describe("SignaturePad", () => {
  beforeEach(() => {
    stubCanvasContext();
  });

  it("renders a canvas and disables Save until a stroke is drawn", () => {
    const onSave = vi.fn();
    const onCancel = vi.fn();
    render(<SignaturePad onSave={onSave} onCancel={onCancel} />);

    expect(screen.getByRole("img", { name: /signature capture area/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /save signature/i })).toBeDisabled();
  });

  it("enables Save after a pointer drag and calls onSave with the canvas data URL", () => {
    const onSave = vi.fn();
    const onCancel = vi.fn();
    render(<SignaturePad onSave={onSave} onCancel={onCancel} />);

    const canvas = screen.getByRole("img", { name: /signature capture area/i });
    fireEvent.pointerDown(canvas, { clientX: 10, clientY: 10, pointerId: 1 });
    fireEvent.pointerMove(canvas, { clientX: 20, clientY: 20, pointerId: 1 });
    fireEvent.pointerUp(canvas, { pointerId: 1 });

    const saveButton = screen.getByRole("button", { name: /save signature/i });
    expect(saveButton).toBeEnabled();

    fireEvent.click(saveButton);
    expect(onSave).toHaveBeenCalledWith("data:image/png;base64,FAKESIGNATUREDATA");
  });

  it("clears the stroke state when Clear is pressed", () => {
    const onSave = vi.fn();
    const onCancel = vi.fn();
    render(<SignaturePad onSave={onSave} onCancel={onCancel} />);

    const canvas = screen.getByRole("img", { name: /signature capture area/i });
    fireEvent.pointerDown(canvas, { clientX: 10, clientY: 10, pointerId: 1 });
    fireEvent.pointerMove(canvas, { clientX: 20, clientY: 20, pointerId: 1 });
    fireEvent.pointerUp(canvas, { pointerId: 1 });
    expect(screen.getByRole("button", { name: /save signature/i })).toBeEnabled();

    fireEvent.click(screen.getByText("Clear"));
    expect(screen.getByRole("button", { name: /save signature/i })).toBeDisabled();
  });

  it("calls onCancel when Cancel is clicked", () => {
    const onSave = vi.fn();
    const onCancel = vi.fn();
    render(<SignaturePad onSave={onSave} onCancel={onCancel} />);

    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("disables the save/cancel buttons while saving", () => {
    render(<SignaturePad onSave={vi.fn()} onCancel={vi.fn()} saving />);
    expect(screen.getByRole("button", { name: /cancel/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /saving/i })).toBeDisabled();
  });
});
