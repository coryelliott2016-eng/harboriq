import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { inventoryApi, purchaseOrdersApi, vendorsApi } from "../lib/services";
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
import type {
  InventoryItem,
  PurchaseOrder,
  PurchaseOrderLineItemInput,
  PurchaseOrderStatus,
  ReorderSuggestion,
} from "../types/api";

const STATUS_TONE: Record<PurchaseOrderStatus, "slate" | "blue" | "green" | "red"> = {
  draft: "slate",
  submitted: "blue",
  received: "green",
  cancelled: "red",
};

// Phase 13: purchase orders (draft -> submitted -> received) plus the
// low-stock reorder-suggestions panel. Generating a PO from suggestions
// only ever produces a draft -- a human still has to review and submit it;
// see app/services/purchase_orders.generate_draft_from_suggestions for why
// this is a deliberate scope boundary, not a missing "auto-order" feature.
export function PurchaseOrdersPage() {
  const { user } = useAuth();
  const canWrite = canManageOperations(user?.role);
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [showCreate, setShowCreate] = useState(false);
  const [receiving, setReceiving] = useState<PurchaseOrder | null>(null);

  const posQuery = useQuery({
    queryKey: ["purchase-orders", { statusFilter }],
    queryFn: () => purchaseOrdersApi.list(statusFilter || undefined),
  });

  const vendorsQuery = useQuery({ queryKey: ["vendors"], queryFn: () => vendorsApi.list() });
  const itemsQuery = useQuery({ queryKey: ["inventory-all"], queryFn: () => inventoryApi.list({ limit: 200 }) });
  const suggestionsQuery = useQuery({
    queryKey: ["reorder-suggestions"],
    queryFn: () => inventoryApi.reorderSuggestions(),
  });

  const vendorNameById = new Map((vendorsQuery.data ?? []).map((v) => [v.id, v.name]));
  const itemNameById = new Map((itemsQuery.data ?? []).map((i) => [i.id, i.name]));

  function refresh() {
    queryClient.invalidateQueries({ queryKey: ["purchase-orders"] });
    queryClient.invalidateQueries({ queryKey: ["reorder-suggestions"] });
    queryClient.invalidateQueries({ queryKey: ["inventory"] });
    queryClient.invalidateQueries({ queryKey: ["inventory-all"] });
  }

  const submitMutation = useMutation({
    mutationFn: (id: string) => purchaseOrdersApi.submit(id),
    onSuccess: refresh,
  });
  const cancelMutation = useMutation({
    mutationFn: (id: string) => purchaseOrdersApi.cancel(id),
    onSuccess: refresh,
  });

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Purchase orders</h1>
          <p className="mt-1 text-sm text-slate-500">
            Draft, submit, and receive orders against your vendors. Receiving is what actually
            increases stock on hand.
          </p>
        </div>
        {canWrite && <Button onClick={() => setShowCreate(true)}>New draft PO</Button>}
      </div>

      {canWrite && (
        <ReorderSuggestionsPanel
          suggestions={suggestionsQuery.data ?? []}
          isLoading={suggestionsQuery.isLoading}
          vendors={vendorsQuery.data ?? []}
          onGenerated={refresh}
        />
      )}

      <div className="flex items-center gap-3">
        <select
          className={inputClass}
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="">All statuses</option>
          <option value="draft">Draft</option>
          <option value="submitted">Submitted</option>
          <option value="received">Received</option>
          <option value="cancelled">Cancelled</option>
        </select>
      </div>

      {posQuery.isLoading && <Spinner label="Loading purchase orders…" />}
      {posQuery.isError && (
        <ErrorBanner
          message={
            posQuery.error instanceof ApiError ? posQuery.error.message : "Failed to load purchase orders."
          }
        />
      )}
      {posQuery.data && posQuery.data.length === 0 && <EmptyState message="No purchase orders yet." />}

      {posQuery.data && posQuery.data.length > 0 && (
        <Card className="overflow-hidden">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Vendor</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Line items</th>
                <th className="px-4 py-3">Total cost</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {posQuery.data.map((po) => {
                const total = po.line_items.reduce(
                  (sum, li) => sum + li.quantity_ordered * parseFloat(li.unit_cost),
                  0,
                );
                return (
                  <tr key={po.id}>
                    <td className="px-4 py-3 font-medium text-slate-900">
                      {vendorNameById.get(po.vendor_id) ?? po.vendor_id}
                    </td>
                    <td className="px-4 py-3">
                      <Badge tone={STATUS_TONE[po.status]}>{po.status}</Badge>
                    </td>
                    <td className="px-4 py-3 text-slate-600">
                      {po.line_items
                        .map(
                          (li) =>
                            `${itemNameById.get(li.inventory_item_id) ?? li.inventory_item_id} (${li.quantity_received}/${li.quantity_ordered})`,
                        )
                        .join(", ")}
                    </td>
                    <td className="px-4 py-3 text-slate-600">{money(total)}</td>
                    <td className="px-4 py-3 text-right">
                      {canWrite && po.status === "draft" && (
                        <div className="flex justify-end gap-2">
                          <Button
                            variant="secondary"
                            onClick={() => cancelMutation.mutate(po.id)}
                            disabled={cancelMutation.isPending}
                          >
                            Cancel
                          </Button>
                          <Button
                            onClick={() => submitMutation.mutate(po.id)}
                            disabled={submitMutation.isPending}
                          >
                            Submit
                          </Button>
                        </div>
                      )}
                      {canWrite && po.status === "submitted" && (
                        <Button onClick={() => setReceiving(po)}>Receive</Button>
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
        <CreatePOModal
          vendors={vendorsQuery.data ?? []}
          items={itemsQuery.data ?? []}
          onClose={() => setShowCreate(false)}
          onSaved={() => {
            setShowCreate(false);
            refresh();
          }}
        />
      )}
      {receiving && (
        <ReceiveModal
          po={receiving}
          itemNameById={itemNameById}
          onClose={() => setReceiving(null)}
          onSaved={() => {
            setReceiving(null);
            refresh();
          }}
        />
      )}
    </div>
  );
}

function ReorderSuggestionsPanel({
  suggestions,
  isLoading,
  vendors,
  onGenerated,
}: {
  suggestions: ReorderSuggestion[];
  isLoading: boolean;
  vendors: { id: string; name: string }[];
  onGenerated: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [lastCreated, setLastCreated] = useState<string | null>(null);

  const generateMutation = useMutation({
    mutationFn: (input: { vendor_id: string; item_ids: string[] }) =>
      inventoryApi.generatePurchaseOrder(input),
    onSuccess: (po) => {
      setError(null);
      setLastCreated(po.id);
      onGenerated();
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : "Failed to generate purchase order."),
  });

  const vendorNameById = new Map(vendors.map((v) => [v.id, v.name]));
  const groups = new Map<string, ReorderSuggestion[]>();
  for (const s of suggestions) {
    const key = s.default_vendor_id ?? "__unassigned__";
    groups.set(key, [...(groups.get(key) ?? []), s]);
  }

  if (isLoading) return <Spinner label="Checking low-stock items…" />;
  if (suggestions.length === 0) return null;

  return (
    <Card className="p-4">
      <h2 className="text-sm font-semibold text-slate-900">Reorder suggestions</h2>
      <p className="mt-1 text-xs text-slate-500">
        Items below their reorder point, grouped by default vendor. One click drafts a PO — it is
        NOT submitted automatically; you still review and submit it yourself.
      </p>
      {error && (
        <div className="mt-3">
          <ErrorBanner message={error} />
        </div>
      )}
      {lastCreated && (
        <p className="mt-3 text-xs text-green-700">Draft PO created — find it in the list below.</p>
      )}
      <div className="mt-3 flex flex-col gap-3">
        {[...groups.entries()].map(([vendorId, items]) => (
          <div key={vendorId} className="flex items-center justify-between rounded-md border border-amber-200 bg-amber-50 px-4 py-2">
            <div className="text-sm text-slate-700">
              <strong>
                {vendorId === "__unassigned__" ? "No default vendor" : vendorNameById.get(vendorId) ?? vendorId}
              </strong>
              : {items.map((i) => `${i.name} (${i.quantity_on_hand}/${i.reorder_point})`).join(", ")}
            </div>
            {vendorId !== "__unassigned__" && (
              <Button
                variant="secondary"
                disabled={generateMutation.isPending}
                onClick={() =>
                  generateMutation.mutate({ vendor_id: vendorId, item_ids: items.map((i) => i.id) })
                }
              >
                Draft PO
              </Button>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}

function CreatePOModal({
  vendors,
  items,
  onClose,
  onSaved,
}: {
  vendors: { id: string; name: string }[];
  items: InventoryItem[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [vendorId, setVendorId] = useState("");
  const [lines, setLines] = useState<PurchaseOrderLineItemInput[]>([
    { inventory_item_id: "", quantity_ordered: 1, unit_cost: "0" },
  ]);
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      purchaseOrdersApi.create({
        vendor_id: vendorId,
        line_items: lines.filter((l) => l.inventory_item_id),
      }),
    onSuccess: onSaved,
    onError: (err) => setError(err instanceof ApiError ? err.message : "Failed to create draft PO."),
  });

  function updateLine(idx: number, patch: Partial<PurchaseOrderLineItemInput>) {
    setLines((prev) => prev.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    mutation.mutate();
  }

  return (
    <Modal title="New draft purchase order" onClose={onClose}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        {error && <ErrorBanner message={error} />}
        <Field label="Vendor">
          <select required className={inputClass} value={vendorId} onChange={(e) => setVendorId(e.target.value)}>
            <option value="">Select a vendor…</option>
            {vendors.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
        </Field>
        <div className="flex flex-col gap-2">
          <span className="text-sm font-medium text-slate-700">Line items</span>
          {lines.map((line, idx) => (
            <div key={idx} className="flex items-center gap-2">
              <select
                className={inputClass}
                value={line.inventory_item_id}
                onChange={(e) => updateLine(idx, { inventory_item_id: e.target.value })}
              >
                <option value="">Select item…</option>
                {items.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.name}
                  </option>
                ))}
              </select>
              <input
                type="number"
                min={1}
                className={`${inputClass} w-24`}
                value={line.quantity_ordered}
                onChange={(e) => updateLine(idx, { quantity_ordered: Number(e.target.value) })}
              />
              <input
                type="number"
                step="0.01"
                min="0"
                className={`${inputClass} w-28`}
                value={line.unit_cost}
                onChange={(e) => updateLine(idx, { unit_cost: e.target.value })}
              />
              <Button
                type="button"
                variant="secondary"
                onClick={() => setLines((prev) => prev.filter((_, i) => i !== idx))}
              >
                Remove
              </Button>
            </div>
          ))}
          <Button
            type="button"
            variant="secondary"
            onClick={() =>
              setLines((prev) => [...prev, { inventory_item_id: "", quantity_ordered: 1, unit_cost: "0" }])
            }
          >
            Add line
          </Button>
        </div>
        <div className="mt-2 flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? "Creating…" : "Create draft"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function ReceiveModal({
  po,
  itemNameById,
  onClose,
  onSaved,
}: {
  po: PurchaseOrder;
  itemNameById: Map<string, string>;
  onClose: () => void;
  onSaved: () => void;
}) {
  const outstanding = po.line_items.filter((li) => li.quantity_received < li.quantity_ordered);
  const [quantities, setQuantities] = useState<Record<string, number>>(
    Object.fromEntries(outstanding.map((li) => [li.id, li.quantity_ordered - li.quantity_received])),
  );
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      purchaseOrdersApi.receive(po.id, {
        receipts: outstanding
          .map((li) => ({ line_item_id: li.id, quantity: quantities[li.id] ?? 0 }))
          .filter((r) => r.quantity > 0),
      }),
    onSuccess: onSaved,
    onError: (err) => setError(err instanceof ApiError ? err.message : "Failed to receive shipment."),
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    mutation.mutate();
  }

  return (
    <Modal title="Receive shipment" onClose={onClose}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        {error && <ErrorBanner message={error} />}
        <p className="text-xs text-slate-500">
          Enter the quantity actually received for each line. Partial receipts are fine — the
          order stays visible with what's still outstanding.
        </p>
        {outstanding.map((li) => (
          <Field
            key={li.id}
            label={`${itemNameById.get(li.inventory_item_id) ?? li.inventory_item_id} (ordered ${li.quantity_ordered}, received so far ${li.quantity_received})`}
          >
            <input
              type="number"
              min={0}
              max={li.quantity_ordered - li.quantity_received}
              className={inputClass}
              value={quantities[li.id] ?? 0}
              onChange={(e) =>
                setQuantities((prev) => ({ ...prev, [li.id]: Number(e.target.value) }))
              }
            />
          </Field>
        ))}
        <div className="mt-2 flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? "Recording…" : "Record receipt"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
