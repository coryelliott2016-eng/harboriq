import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { customersApi, slipReservationsApi, slipsApi, vesselsApi } from "../lib/services";
import { ApiError } from "../lib/api";
import { canManageOperations, useAuth } from "../context/auth";
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
} from "../components/ui";
import { customerName } from "../lib/format";
import type { SlipReservation, SlipReservationInput, SlipReservationStatus } from "../types/api";

const STATUS_TONE: Record<SlipReservationStatus, "slate" | "blue" | "green" | "red" | "amber"> = {
  pending: "amber",
  confirmed: "blue",
  checked_in: "green",
  checked_out: "slate",
  cancelled: "red",
};

// Phase 15: reservation list + lifecycle actions (pending -> confirmed ->
// checked_in -> checked_out, or cancelled from pending/confirmed). Mirrors
// PurchaseOrdersPage.tsx's pattern of one mutation per lifecycle endpoint
// plus a status-conditional action column, and adds the billing actions
// (generate storage charge / generate invoice) once a stay is checked out.
export function SlipReservationsPage() {
  const { user } = useAuth();
  const canWrite = canManageOperations(user?.role);
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [billing, setBilling] = useState<SlipReservation | null>(null);

  const reservationsQuery = useQuery({
    queryKey: ["slip-reservations", { statusFilter }],
    queryFn: () => slipReservationsApi.list({ status: statusFilter || undefined }),
  });
  const slipsQuery = useQuery({ queryKey: ["slips-all"], queryFn: () => slipsApi.list() });
  const customersQuery = useQuery({ queryKey: ["customers"], queryFn: () => customersApi.list() });

  const slipById = new Map((slipsQuery.data ?? []).map((s) => [s.id, s]));
  const customerById = new Map((customersQuery.data ?? []).map((c) => [c.id, c]));

  function refresh() {
    queryClient.invalidateQueries({ queryKey: ["slip-reservations"] });
    queryClient.invalidateQueries({ queryKey: ["slips-all"] });
    queryClient.invalidateQueries({ queryKey: ["slips"] });
  }

  const confirmMutation = useMutation({
    mutationFn: (id: string) => slipReservationsApi.confirm(id),
    onSuccess: refresh,
  });
  const checkInMutation = useMutation({
    mutationFn: (id: string) => slipReservationsApi.checkIn(id),
    onSuccess: refresh,
  });
  const checkOutMutation = useMutation({
    mutationFn: (id: string) => slipReservationsApi.checkOut(id),
    onSuccess: refresh,
  });
  const cancelMutation = useMutation({
    mutationFn: (id: string) => slipReservationsApi.cancel(id),
    onSuccess: refresh,
  });

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Slip reservations</h1>
          <p className="mt-1 text-sm text-slate-500">
            Book, confirm, check in/out, and bill slip stays. Double-bookings are rejected by the
            database itself, not just this UI.
          </p>
        </div>
        {canWrite && <Button onClick={() => setShowCreate(true)}>New reservation</Button>}
      </div>

      <div className="flex items-center gap-3">
        <select
          className={inputClass}
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="">All statuses</option>
          <option value="pending">Pending</option>
          <option value="confirmed">Confirmed</option>
          <option value="checked_in">Checked in</option>
          <option value="checked_out">Checked out</option>
          <option value="cancelled">Cancelled</option>
        </select>
      </div>

      {reservationsQuery.isLoading && <Spinner label="Loading reservations…" />}
      {reservationsQuery.isError && (
        <ErrorBanner
          message={
            reservationsQuery.error instanceof ApiError
              ? reservationsQuery.error.message
              : "Failed to load reservations."
          }
        />
      )}
      {reservationsQuery.data && reservationsQuery.data.length === 0 && (
        <EmptyState message="No reservations yet." />
      )}

      {reservationsQuery.data && reservationsQuery.data.length > 0 && (
        <Card className="overflow-hidden">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Slip</th>
                <th className="px-4 py-3">Customer</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Dates</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {reservationsQuery.data.map((res) => {
                const slip = slipById.get(res.slip_id);
                const customer = customerById.get(res.customer_id);
                return (
                  <tr key={res.id}>
                    <td className="px-4 py-3 font-medium text-slate-900">
                      {slip?.identifier ?? res.slip_id}
                    </td>
                    <td className="px-4 py-3 text-slate-600">
                      {customer ? customerName(customer) : res.customer_id}
                    </td>
                    <td className="px-4 py-3">
                      <Badge tone={STATUS_TONE[res.status]}>{res.status.replace("_", " ")}</Badge>
                    </td>
                    <td className="px-4 py-3 text-slate-600">
                      {res.start_date} → {res.end_date}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {canWrite && (
                        <div className="flex justify-end gap-2">
                          {res.status === "pending" && (
                            <>
                              <Button
                                variant="secondary"
                                disabled={cancelMutation.isPending}
                                onClick={() => cancelMutation.mutate(res.id)}
                              >
                                Cancel
                              </Button>
                              <Button
                                disabled={confirmMutation.isPending}
                                onClick={() => confirmMutation.mutate(res.id)}
                              >
                                Confirm
                              </Button>
                            </>
                          )}
                          {res.status === "confirmed" && (
                            <>
                              <Button
                                variant="secondary"
                                disabled={cancelMutation.isPending}
                                onClick={() => cancelMutation.mutate(res.id)}
                              >
                                Cancel
                              </Button>
                              <Button
                                disabled={checkInMutation.isPending}
                                onClick={() => checkInMutation.mutate(res.id)}
                              >
                                Check in
                              </Button>
                            </>
                          )}
                          {res.status === "checked_in" && (
                            <Button
                              disabled={checkOutMutation.isPending}
                              onClick={() => checkOutMutation.mutate(res.id)}
                            >
                              Check out
                            </Button>
                          )}
                          {res.status === "checked_out" && (
                            <Button variant="secondary" onClick={() => setBilling(res)}>
                              Bill stay
                            </Button>
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}

      {showCreate && (
        <CreateReservationModal
          onClose={() => setShowCreate(false)}
          onSaved={() => {
            setShowCreate(false);
            refresh();
          }}
        />
      )}
      {billing && (
        <BillingModal
          reservation={billing}
          onClose={() => setBilling(null)}
          onSaved={() => {
            setBilling(null);
            refresh();
          }}
        />
      )}
    </div>
  );
}

function CreateReservationModal({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const slipsQuery = useQuery({ queryKey: ["slips-all"], queryFn: () => slipsApi.list() });
  const customersQuery = useQuery({ queryKey: ["customers"], queryFn: () => customersApi.list() });
  const [customerId, setCustomerId] = useState("");
  const vesselsQuery = useQuery({
    queryKey: ["vessels", customerId],
    queryFn: () => vesselsApi.list(customerId),
    enabled: !!customerId,
  });
  const [slipId, setSlipId] = useState("");
  const [vesselId, setVesselId] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => {
      const body: SlipReservationInput = {
        slip_id: slipId,
        customer_id: customerId,
        vessel_id: vesselId || null,
        start_date: startDate,
        end_date: endDate,
        notes: notes || null,
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
    <Modal title="New reservation" onClose={onClose}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        {error && <ErrorBanner message={error} />}
        <Field label="Slip">
          <select required className={inputClass} value={slipId} onChange={(e) => setSlipId(e.target.value)}>
            <option value="">Select a slip…</option>
            {(slipsQuery.data ?? []).map((s) => (
              <option key={s.id} value={s.id}>
                {s.identifier}
              </option>
            ))}
          </select>
        </Field>
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
        <Field label="Notes (optional)">
          <textarea
            className={inputClass}
            rows={3}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </Field>
        <div className="mt-2 flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? "Creating…" : "Create"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function BillingModal({
  reservation,
  onClose,
  onSaved,
}: {
  reservation: SlipReservation;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [chargeGenerated, setChargeGenerated] = useState(false);
  const [invoiceCreated, setInvoiceCreated] = useState(false);

  const chargeMutation = useMutation({
    mutationFn: () => slipReservationsApi.generateStorageCharge(reservation.id),
    onSuccess: () => setChargeGenerated(true),
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : "Failed to generate storage charge."),
  });

  const invoiceMutation = useMutation({
    mutationFn: () => slipReservationsApi.generateInvoice(reservation.id),
    onSuccess: () => {
      setInvoiceCreated(true);
      onSaved();
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : "Failed to generate invoice."),
  });

  return (
    <Modal title="Bill slip stay" onClose={onClose}>
      <div className="flex flex-col gap-4">
        {error && <ErrorBanner message={error} />}
        <p className="text-sm text-slate-600">
          Stay from {reservation.start_date} to {reservation.end_date}. First generate the storage
          line item (nights × daily rate), then generate the invoice — the same invoicing pipeline
          used for job billing.
        </p>
        <div className="flex justify-end gap-2">
          <Button
            variant="secondary"
            disabled={chargeMutation.isPending || chargeGenerated}
            onClick={() => chargeMutation.mutate()}
          >
            {chargeGenerated ? "Charge generated" : "Generate storage charge"}
          </Button>
          <Button
            disabled={invoiceMutation.isPending || invoiceCreated}
            onClick={() => invoiceMutation.mutate()}
          >
            {invoiceCreated ? "Invoice created" : "Generate invoice"}
          </Button>
        </div>
        <div className="mt-2 flex justify-end">
          <Button type="button" variant="secondary" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </Modal>
  );
}
