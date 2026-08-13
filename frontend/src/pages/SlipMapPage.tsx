import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { customersApi, slipReservationsApi, slipsApi, vesselsApi } from "../lib/services";
import { ApiError } from "../lib/api";
import { canManageOperations, useAuth } from "../context/auth";
import {
  Button,
  Card,
  ErrorBanner,
  Field,
  Modal,
  Spinner,
  inputClass,
} from "../components/ui";
import { customerName } from "../lib/format";
import type { Slip, SlipReservationInput, SlipStatus } from "../types/api";

const STATUS_COLOR: Record<SlipStatus, string> = {
  available: "bg-green-100 border-green-400 text-green-900 hover:bg-green-200",
  occupied: "bg-blue-100 border-blue-400 text-blue-900 hover:bg-blue-200",
  reserved: "bg-amber-100 border-amber-400 text-amber-900 hover:bg-amber-200",
  maintenance: "bg-red-100 border-red-400 text-red-900 hover:bg-red-200",
};

// Phase 15: the visual, click-to-reserve marina map. Deliberately a CSS
// grid rather than Leaflet/GPS (Phase 11's approach for job dispatch) --
// slips have no meaningful geospatial coordinates worth plotting on a real
// map for the vast majority of marinas (a marina's layout is a grid of
// fingers/racks, not a set of lat/lng points spread over a region). `slips`
// does carry optional latitude/longitude columns for the rare marina that
// wants a georeferenced overlay later, but building that UI now would be
// speculative; see docs/COMPETITIVE_PARITY_ROADMAP.md's Phase 15 section.
export function SlipMapPage() {
  const { user } = useAuth();
  const canWrite = canManageOperations(user?.role);
  const queryClient = useQueryClient();
  const [typeFilter, setTypeFilter] = useState<string>("");
  const [selected, setSelected] = useState<Slip | null>(null);

  const slipsQuery = useQuery({
    queryKey: ["slips", { typeFilter }],
    queryFn: () => slipsApi.list({ slip_type: typeFilter || undefined }),
  });

  const grouped = useMemo(() => {
    const groups = new Map<string, Slip[]>();
    for (const slip of slipsQuery.data ?? []) {
      const key = slip.slip_type;
      groups.set(key, [...(groups.get(key) ?? []), slip].sort((a, b) => a.identifier.localeCompare(b.identifier)));
    }
    return groups;
  }, [slipsQuery.data]);

  function refresh() {
    queryClient.invalidateQueries({ queryKey: ["slips"] });
    queryClient.invalidateQueries({ queryKey: ["slip-reservations"] });
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Slip map</h1>
          <p className="mt-1 text-sm text-slate-500">
            Color-coded by status. Click an available slip to start a reservation.
          </p>
        </div>
        <select
          className={inputClass}
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
        >
          <option value="">All types</option>
          <option value="wet_slip">Wet slips</option>
          <option value="dry_stack">Dry stack</option>
          <option value="mooring">Moorings</option>
        </select>
      </div>

      <div className="flex flex-wrap items-center gap-4 text-xs text-slate-600">
        {(["available", "occupied", "reserved", "maintenance"] as SlipStatus[]).map((s) => (
          <div key={s} className="flex items-center gap-1.5">
            <span className={`h-3 w-3 rounded border ${STATUS_COLOR[s].split(" ").slice(0, 2).join(" ")}`} />
            {s}
          </div>
        ))}
      </div>

      {slipsQuery.isLoading && <Spinner label="Loading slip map…" />}
      {slipsQuery.isError && (
        <ErrorBanner
          message={slipsQuery.error instanceof ApiError ? slipsQuery.error.message : "Failed to load slips."}
        />
      )}

      {[...grouped.entries()].map(([type, slips]) => (
        <Card key={type} className="p-4">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
            {type.replace("_", " ")}
          </h2>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(88px,1fr))] gap-2">
            {slips.map((slip) => (
              <button
                key={slip.id}
                type="button"
                onClick={() => setSelected(slip)}
                className={`flex flex-col items-center justify-center rounded-md border-2 px-2 py-3 text-xs font-medium transition-colors ${STATUS_COLOR[slip.status]}`}
              >
                <span className="font-semibold">{slip.identifier}</span>
                <span className="capitalize">{slip.status}</span>
              </button>
            ))}
          </div>
        </Card>
      ))}

      {selected && (
        <SlipDetailModal
          slip={selected}
          canWrite={canWrite}
          onClose={() => setSelected(null)}
          onSaved={() => {
            setSelected(null);
            refresh();
          }}
        />
      )}
    </div>
  );
}

function SlipDetailModal({
  slip,
  canWrite,
  onClose,
  onSaved,
}: {
  slip: Slip;
  canWrite: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [showReserve, setShowReserve] = useState(false);

  return (
    <Modal title={`Slip ${slip.identifier}`} onClose={onClose}>
      <div className="flex flex-col gap-3 text-sm text-slate-700">
        <dl className="grid grid-cols-2 gap-2">
          <dt className="text-slate-500">Type</dt>
          <dd className="capitalize">{slip.slip_type.replace("_", " ")}</dd>
          <dt className="text-slate-500">Status</dt>
          <dd className="capitalize">{slip.status}</dd>
          <dt className="text-slate-500">Daily rate</dt>
          <dd>${slip.daily_rate}</dd>
          <dt className="text-slate-500">Monthly rate</dt>
          <dd>${slip.monthly_rate}</dd>
          {slip.notes && (
            <>
              <dt className="text-slate-500">Notes</dt>
              <dd>{slip.notes}</dd>
            </>
          )}
        </dl>
        {canWrite && slip.status === "available" && !showReserve && (
          <Button onClick={() => setShowReserve(true)}>Reserve this slip</Button>
        )}
        {showReserve && (
          <QuickReserveForm slip={slip} onCancel={() => setShowReserve(false)} onSaved={onSaved} />
        )}
        <div className="mt-2 flex justify-end">
          <Button type="button" variant="secondary" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function QuickReserveForm({
  slip,
  onCancel,
  onSaved,
}: {
  slip: Slip;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const customersQuery = useQuery({ queryKey: ["customers"], queryFn: () => customersApi.list() });
  const [customerId, setCustomerId] = useState("");
  const vesselsQuery = useQuery({
    queryKey: ["vessels", customerId],
    queryFn: () => vesselsApi.list(customerId),
    enabled: !!customerId,
  });
  const [vesselId, setVesselId] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => {
      const body: SlipReservationInput = {
        slip_id: slip.id,
        customer_id: customerId,
        vessel_id: vesselId || null,
        start_date: startDate,
        end_date: endDate,
      };
      return slipReservationsApi.create(body);
    },
    onSuccess: onSaved,
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : "Failed to create reservation."),
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    mutation.mutate();
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3 rounded-md border border-slate-200 p-3">
      {error && <ErrorBanner message={error} />}
      <Field label="Customer">
        <select
          required
          className={inputClass}
          value={customerId}
          onChange={(e) => {
            setCustomerId(e.target.value);
            setVesselId("");
          }}
        >
          <option value="">Select a customer…</option>
          {(customersQuery.data ?? []).map((c) => (
            <option key={c.id} value={c.id}>
              {customerName(c)}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Vessel (optional)">
        <select className={inputClass} value={vesselId} onChange={(e) => setVesselId(e.target.value)}>
          <option value="">None</option>
          {(vesselsQuery.data ?? []).map((v) => (
            <option key={v.id} value={v.id}>
              {v.name}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Start date">
        <input
          required
          type="date"
          className={inputClass}
          value={startDate}
          onChange={(e) => setStartDate(e.target.value)}
        />
      </Field>
      <Field label="End date">
        <input
          required
          type="date"
          className={inputClass}
          value={endDate}
          onChange={(e) => setEndDate(e.target.value)}
        />
      </Field>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? "Booking…" : "Book"}
        </Button>
      </div>
    </form>
  );
}
