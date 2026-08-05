import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { slipsApi } from "../lib/services";
import { ApiError } from "../lib/api";
import { canManageOperations, useAuth } from "../context/AuthContext";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Field,
  Modal,
  Spinner,
  inputClass,
  money,
} from "../components/ui";
import type { Slip, SlipInput, SlipStatus, SlipType } from "../types/api";

const STATUS_TONE: Record<SlipStatus, "slate" | "blue" | "green" | "red" | "amber"> = {
  available: "green",
  occupied: "blue",
  reserved: "amber",
  maintenance: "red",
};

const TYPE_LABEL: Record<SlipType, string> = {
  wet_slip: "Wet slip",
  dry_stack: "Dry stack",
  mooring: "Mooring",
};

// Phase 15: staff-facing CRUD for the physical inventory of slips/racks --
// the visual, click-to-reserve view lives at SlipMapPage.tsx. This page is
// where new slips get created and dimensions/rates get edited, modeled on
// VendorsPage.tsx's plain list + modal pattern.
export function SlipsPage() {
  const { user } = useAuth();
  const canWrite = canManageOperations(user?.role);
  const queryClient = useQueryClient();
  const [typeFilter, setTypeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<Slip | null>(null);

  const slipsQuery = useQuery({
    queryKey: ["slips", { typeFilter, statusFilter }],
    queryFn: () =>
      slipsApi.list({
        slip_type: typeFilter || undefined,
        status: statusFilter || undefined,
      }),
  });

  function afterSave() {
    queryClient.invalidateQueries({ queryKey: ["slips"] });
    setShowCreate(false);
    setEditing(null);
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Slips</h1>
          <p className="mt-1 text-sm text-slate-500">
            Wet slips, dry-stack rack spaces, and moorings — dimensions and rates. For the
            clickable status map, see Slip map.
          </p>
        </div>
        {canWrite && <Button onClick={() => setShowCreate(true)}>New slip</Button>}
      </div>

      <div className="flex items-center gap-3">
        <select className={inputClass} value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
          <option value="">All types</option>
          <option value="wet_slip">Wet slip</option>
          <option value="dry_stack">Dry stack</option>
          <option value="mooring">Mooring</option>
        </select>
        <select
          className={inputClass}
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="">All statuses</option>
          <option value="available">Available</option>
          <option value="occupied">Occupied</option>
          <option value="reserved">Reserved</option>
          <option value="maintenance">Maintenance</option>
        </select>
      </div>

      {slipsQuery.isLoading && <Spinner label="Loading slips…" />}
      {slipsQuery.isError && (
        <ErrorBanner
          message={slipsQuery.error instanceof ApiError ? slipsQuery.error.message : "Failed to load slips."}
        />
      )}
      {slipsQuery.data && slipsQuery.data.length === 0 && <EmptyState message="No slips yet." />}

      {slipsQuery.data && slipsQuery.data.length > 0 && (
        <Card className="overflow-hidden">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Identifier</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Dimensions</th>
                <th className="px-4 py-3">Daily rate</th>
                <th className="px-4 py-3">Monthly rate</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {slipsQuery.data.map((slip) => (
                <tr key={slip.id}>
                  <td className="px-4 py-3 font-medium text-slate-900">{slip.identifier}</td>
                  <td className="px-4 py-3 text-slate-600">{TYPE_LABEL[slip.slip_type]}</td>
                  <td className="px-4 py-3">
                    <Badge tone={STATUS_TONE[slip.status]}>{slip.status}</Badge>
                  </td>
                  <td className="px-4 py-3 text-slate-600">
                    {slip.slip_type === "dry_stack"
                      ? `Level ${slip.rack_level ?? "—"}, ${slip.rack_position ?? "—"}`
                      : `${slip.length_ft ?? "—"}ft x ${slip.width_ft ?? "—"}ft${
                          slip.depth_ft ? `, ${slip.depth_ft}ft depth` : ""
                        }`}
                  </td>
                  <td className="px-4 py-3 text-slate-600">{money(slip.daily_rate)}</td>
                  <td className="px-4 py-3 text-slate-600">{money(slip.monthly_rate)}</td>
                  <td className="px-4 py-3 text-right">
                    {canWrite && (
                      <Button variant="secondary" onClick={() => setEditing(slip)}>
                        Edit
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {showCreate && <SlipModal onClose={() => setShowCreate(false)} onSaved={afterSave} />}
      {editing && <SlipModal slip={editing} onClose={() => setEditing(null)} onSaved={afterSave} />}
    </div>
  );
}

function SlipModal({
  slip,
  onClose,
  onSaved,
}: {
  slip?: Slip;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [identifier, setIdentifier] = useState(slip?.identifier ?? "");
  const [slipType, setSlipType] = useState<SlipType>(slip?.slip_type ?? "wet_slip");
  const [status, setStatus] = useState<SlipStatus>(slip?.status ?? "available");
  const [lengthFt, setLengthFt] = useState(slip?.length_ft ?? "");
  const [widthFt, setWidthFt] = useState(slip?.width_ft ?? "");
  const [depthFt, setDepthFt] = useState(slip?.depth_ft ?? "");
  const [rackLevel, setRackLevel] = useState(slip?.rack_level != null ? String(slip.rack_level) : "");
  const [rackPosition, setRackPosition] = useState(slip?.rack_position ?? "");
  const [dailyRate, setDailyRate] = useState(slip?.daily_rate ?? "0");
  const [monthlyRate, setMonthlyRate] = useState(slip?.monthly_rate ?? "0");
  const [notes, setNotes] = useState(slip?.notes ?? "");
  const [error, setError] = useState<string | null>(null);

  const isDryStack = slipType === "dry_stack";

  const mutation = useMutation({
    mutationFn: () => {
      const body: SlipInput = {
        identifier,
        slip_type: slipType,
        status,
        length_ft: isDryStack ? null : lengthFt || null,
        width_ft: isDryStack ? null : widthFt || null,
        depth_ft: isDryStack ? null : depthFt || null,
        rack_level: isDryStack && rackLevel ? Number(rackLevel) : null,
        rack_position: isDryStack ? rackPosition || null : null,
        daily_rate: dailyRate,
        monthly_rate: monthlyRate,
        notes: notes || null,
      };
      return slip ? slipsApi.update(slip.id, body) : slipsApi.create(body);
    },
    onSuccess: onSaved,
    onError: (err) => setError(err instanceof ApiError ? err.message : "Failed to save slip."),
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    mutation.mutate();
  }

  return (
    <Modal title={slip ? `Edit ${slip.identifier}` : "New slip"} onClose={onClose}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        {error && <ErrorBanner message={error} />}
        <Field label="Identifier">
          <input
            required
            className={inputClass}
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
          />
        </Field>
        <Field label="Type">
          <select
            className={inputClass}
            value={slipType}
            onChange={(e) => setSlipType(e.target.value as SlipType)}
          >
            <option value="wet_slip">Wet slip</option>
            <option value="dry_stack">Dry stack</option>
            <option value="mooring">Mooring</option>
          </select>
        </Field>
        <Field label="Status">
          <select
            className={inputClass}
            value={status}
            onChange={(e) => setStatus(e.target.value as SlipStatus)}
          >
            <option value="available">Available</option>
            <option value="occupied">Occupied</option>
            <option value="reserved">Reserved</option>
            <option value="maintenance">Maintenance</option>
          </select>
        </Field>
        {isDryStack ? (
          <>
            <Field label="Rack level">
              <input
                type="number"
                min={0}
                className={inputClass}
                value={rackLevel}
                onChange={(e) => setRackLevel(e.target.value)}
              />
            </Field>
            <Field label="Rack position">
              <input
                className={inputClass}
                value={rackPosition}
                onChange={(e) => setRackPosition(e.target.value)}
              />
            </Field>
          </>
        ) : (
          <>
            <Field label="Length (ft)">
              <input
                className={inputClass}
                value={lengthFt ?? ""}
                onChange={(e) => setLengthFt(e.target.value)}
              />
            </Field>
            <Field label="Width (ft)">
              <input
                className={inputClass}
                value={widthFt ?? ""}
                onChange={(e) => setWidthFt(e.target.value)}
              />
            </Field>
            <Field label="Depth (ft, optional)">
              <input
                className={inputClass}
                value={depthFt ?? ""}
                onChange={(e) => setDepthFt(e.target.value)}
              />
            </Field>
          </>
        )}
        <Field label="Daily rate">
          <input
            type="number"
            step="0.01"
            min="0"
            className={inputClass}
            value={dailyRate}
            onChange={(e) => setDailyRate(e.target.value)}
          />
        </Field>
        <Field label="Monthly rate">
          <input
            type="number"
            step="0.01"
            min="0"
            className={inputClass}
            value={monthlyRate}
            onChange={(e) => setMonthlyRate(e.target.value)}
          />
        </Field>
        <Field label="Notes (optional)">
          <textarea
            className={inputClass}
            rows={3}
            value={notes ?? ""}
            onChange={(e) => setNotes(e.target.value)}
          />
        </Field>
        <div className="mt-2 flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? "Saving…" : "Save"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
