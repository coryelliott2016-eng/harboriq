import { useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { Button } from "./ui";

interface SignaturePadProps {
  onSave: (dataUrl: string) => void;
  onCancel: () => void;
  saving?: boolean;
}

/**
 * Digital signature capture (Phase 12), built directly on the HTML5 Canvas
 * API with no dependency, per spec. Draws with pointer events (covers
 * mouse, touch, and stylus in one handler set) and exports a base64 PNG
 * data URL on save, which the caller strips the `data:...;base64,` prefix
 * from before sending to the backend (see JobAttachmentCreate's validator
 * in app/schemas/field_app.py, which also accepts the raw prefixed form
 * defensively).
 */
export function SignaturePad({ onSave, onCancel, saving = false }: SignaturePadProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const drawing = useRef(false);
  const [hasStroke, setHasStroke] = useState(false);

  function getContext() {
    const canvas = canvasRef.current;
    if (!canvas) return null;
    return canvas.getContext("2d");
  }

  function pointerPos(e: ReactPointerEvent<HTMLCanvasElement>) {
    const canvas = canvasRef.current!;
    const rect = canvas.getBoundingClientRect();
    return {
      x: ((e.clientX - rect.left) / rect.width) * canvas.width,
      y: ((e.clientY - rect.top) / rect.height) * canvas.height,
    };
  }

  function handlePointerDown(e: ReactPointerEvent<HTMLCanvasElement>) {
    const ctx = getContext();
    if (!ctx) return;
    drawing.current = true;
    const { x, y } = pointerPos(e);
    ctx.beginPath();
    ctx.moveTo(x, y);
    canvasRef.current?.setPointerCapture(e.pointerId);
  }

  function handlePointerMove(e: ReactPointerEvent<HTMLCanvasElement>) {
    if (!drawing.current) return;
    const ctx = getContext();
    if (!ctx) return;
    const { x, y } = pointerPos(e);
    ctx.lineWidth = 2.5;
    ctx.lineCap = "round";
    ctx.strokeStyle = "#0f172a";
    ctx.lineTo(x, y);
    ctx.stroke();
    setHasStroke(true);
  }

  function handlePointerUp() {
    drawing.current = false;
  }

  function handleClear() {
    const canvas = canvasRef.current;
    const ctx = getContext();
    if (!canvas || !ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    setHasStroke(false);
  }

  function handleSave() {
    const canvas = canvasRef.current;
    if (!canvas) return;
    onSave(canvas.toDataURL("image/png"));
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-slate-600">
        Have the customer sign below with a finger or stylus.
      </p>
      <canvas
        ref={canvasRef}
        role="img"
        aria-label="Signature capture area"
        width={600}
        height={220}
        className="w-full touch-none rounded-md border border-slate-300 bg-white"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerLeave={handlePointerUp}
      />
      <div className="flex justify-between gap-2">
        <button
          type="button"
          onClick={handleClear}
          className="text-sm text-slate-500 hover:underline"
        >
          Clear
        </button>
        <div className="flex gap-2">
          <Button type="button" variant="secondary" onClick={onCancel} disabled={saving}>
            Cancel
          </Button>
          <Button type="button" onClick={handleSave} disabled={!hasStroke || saving}>
            {saving ? "Saving…" : "Save signature"}
          </Button>
        </div>
      </div>
    </div>
  );
}
