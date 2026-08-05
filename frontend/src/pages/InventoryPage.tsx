import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { inventoryApi, vendorsApi } from "../lib/services";
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
import type { InventoryItem, InventoryItemInput } from "../types/api";

// Phase 13: full inventory CRUD + SKU/barcode-style lookup + low-stock
// filter. `quantity_on_hand` is deliberately read-only here -- it only ever
// moves through POST /inventory/use (job parts billing) or a received
// purchase order (see PurchaseOrdersPage.tsx), never a direct edit, so
// stock counts always trace back to a real event.
export function InventoryPage() {
  const { user } = useAuth();
  const canWrite = canManageOperations(user?.role);
  const queryClient = useQueryClient();
  const [lowStockOnly, setLowStockOnly] = useState(false);
  const [search, setSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<InventoryItem | null>(null);
  const [skuInput, setSkuInput] = useState("");
  const [lookupResult, setLookupResult] = useState<InventoryItem | null>(null);
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [scanSupported] = useState(() => "BarcodeDetector" in globalThis);

  const itemsQuery = useQuery({
    queryKey: ["inventory", { search, lowStockOnly }],
    queryFn: () => inventoryApi.list({ search: search || undefined, low_stock_only: lowStockOnly }),
  });

  const vendorsQuery = useQuery({
    queryKey: ["vendors"],
    queryFn: () => vendorsApi.list(),
  });

  const lookupMutation = useMutation({
    mutationFn: (sku: string) => inventoryApi.lookupBySku(sku),
    onSuccess: (item) => {
      setLookupResult(item);
      setLookupError(null);
    },
    onError: (err) => {
      setLookupResult(null);
      setLookupError(err instanceof ApiError ? err.message : "Lookup failed.");
    },
  });

  function handleLookup(e: FormEvent) {
    e.preventDefault();
    if (!skuInput.trim()) return;
    lookupMutation.mutate(skuInput.trim());
  }

  function afterSave() {
    queryClient.invalidateQueries({ queryKey: ["inventory"] });
    setShowCreate(false);
    setEditing(null);
  }

  const vendorNameById = new Map((vendorsQuery.data ?? []).map((v) => [v.id, v.name]));

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Inventory</h1>
          <p className="mt-1 text-sm text-slate-500">
            Parts on hand, reorder points, and SKU lookup. Stock counts only change through a
            job's parts usage or a received purchase order.
          </p>
        </div>
        {canWrite && <Button onClick={() => setShowCreate(true)}>New item</Button>}
      </div>

      <Card className="p-4">
        <form onSubmit={handleLookup} className="flex flex-wrap items-end gap-3">
          <Field label="Look up by SKU / barcode">
            <input
              className={inputClass}
              placeholder="Scan or type a SKU"
              value={skuInput}
              onChange={(e) => setSkuInput(e.target.value)}
            />
          </Field>
          <Button type="submit" disabled={lookupMutation.isPending}>
            {lookupMutation.isPending ? "Looking up…" : "Look up"}
          </Button>
          {!scanSupported && (
            <span className="text-xs text-slate-400">
              Camera barcode scanning isn't available in this browser (the Barcode Detection API
              is Chrome/Edge/Android-only — not Firefox or Safari/iOS) — type the SKU manually.
            </span>
          )}
        </form>
        {lookupError && (
          <div className="mt-3">
            <ErrorBanner message={lookupError} />
          </div>
        )}
        {lookupResult && (
          <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 px-4 py-3 text-sm">
            <strong>{lookupResult.name}</strong> ({lookupResult.sku}) — on hand:{" "}
            {lookupResult.quantity_on_hand}, reorder point: {lookupResult.reorder_point}
          </div>
        )}
      </Card>

      <div className="flex flex-wrap items-center gap-3">
        <input
          className={inputClass}
          placeholder="Search by name or SKU"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={lowStockOnly}
            onChange={(e) => setLowStockOnly(e.target.checked)}
          />
          Low stock only
        </label>
      </div>

      {itemsQuery.isLoading && <Spinner label="Loading inventory…" />}
      {itemsQuery.isError && (
        <ErrorBanner
          message={
            itemsQuery.error instanceof ApiError
              ? itemsQuery.error.message
              : "Failed to load inventory."
          }
        />
      )}
      {itemsQuery.data && itemsQuery.data.length === 0 && (
        <EmptyState message="No inventory items match." />
      )}

      {itemsQuery.data && itemsQuery.data.length > 0 && (
        <Card className="overflow-hidden">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">SKU</th>
                <th className="px-4 py-3">On hand</th>
                <th className="px-4 py-3">Reorder point</th>
                <th className="px-4 py-3">Unit cost</th>
                <th className="px-4 py-3">Retail</th>
                <th className="px-4 py-3">Default vendor</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {itemsQuery.data.map((item) => {
                const low = item.quantity_on_hand < item.reorder_point;
                return (
                  <tr key={item.id} className={low ? "bg-amber-50/60" : undefined}>
                    <td className="px-4 py-3 font-medium text-slate-900">{item.name}</td>
                    <td className="px-4 py-3 text-slate-600">{item.sku ?? "—"}</td>
                    <td className="px-4 py-3">
                      <span className="flex items-center gap-1.5">
                        {item.quantity_on_hand}
                        {low && <Badge tone="amber">low</Badge>}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-600">{item.reorder_point}</td>
                    <td className="px-4 py-3 text-slate-600">{money(item.unit_cost)}</td>
                    <td className="px-4 py-3 text-slate-600">{money(item.retail_price)}</td>
                    <td className="px-4 py-3 text-slate-600">
                      {item.default_vendor_id
                        ? vendorNameById.get(item.default_vendor_id) ?? "—"
                        : "—"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {canWrite && (
                        <Button variant="secondary" onClick={() => setEditing(item)}>
                          Edit
                        </Button>
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
        <ItemModal
          vendors={vendorsQuery.data ?? []}
          onClose={() => setShowCreate(false)}
          onSaved={afterSave}
        />
      )}
      {editing && (
        <ItemModal
          item={editing}
          vendors={vendorsQuery.data ?? []}
          onClose={() => setEditing(null)}
          onSaved={afterSave}
        />
      )}
    </div>
  );
}

function ItemModal({
  item,
  vendors,
  onClose,
  onSaved,
}: {
  item?: InventoryItem;
  vendors: { id: string; name: string }[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(item?.name ?? "");
  const [sku, setSku] = useState(item?.sku ?? "");
  const [unitCost, setUnitCost] = useState(item?.unit_cost ?? "0");
  const [retailPrice, setRetailPrice] = useState(item?.retail_price ?? "0");
  const [reorderPoint, setReorderPoint] = useState(item?.reorder_point ?? 0);
  const [defaultVendorId, setDefaultVendorId] = useState(item?.default_vendor_id ?? "");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => {
      const body: InventoryItemInput = {
        name,
        sku: sku || null,
        unit_cost: unitCost,
        retail_price: retailPrice,
        reorder_point: reorderPoint,
        default_vendor_id: defaultVendorId || null,
      };
      return item ? inventoryApi.update(item.id, body) : inventoryApi.create(body);
    },
    onSuccess: onSaved,
    onError: (err) => setError(err instanceof ApiError ? err.message : "Failed to save item."),
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    mutation.mutate();
  }

  return (
    <Modal title={item ? `Edit ${item.name}` : "New inventory item"} onClose={onClose}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        {error && <ErrorBanner message={error} />}
        <Field label="Name">
          <input
            required
            className={inputClass}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        <Field label="SKU (optional)">
          <input className={inputClass} value={sku ?? ""} onChange={(e) => setSku(e.target.value)} />
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Unit cost">
            <input
              type="number"
              step="0.01"
              min="0"
              className={inputClass}
              value={unitCost}
              onChange={(e) => setUnitCost(e.target.value)}
            />
          </Field>
          <Field label="Retail price">
            <input
              type="number"
              step="0.01"
              min="0"
              className={inputClass}
              value={retailPrice}
              onChange={(e) => setRetailPrice(e.target.value)}
            />
          </Field>
        </div>
        <Field label="Reorder point">
          <input
            type="number"
            min="0"
            className={inputClass}
            value={reorderPoint}
            onChange={(e) => setReorderPoint(Number(e.target.value))}
          />
        </Field>
        <Field label="Default vendor (optional)">
          <select
            className={inputClass}
            value={defaultVendorId ?? ""}
            onChange={(e) => setDefaultVendorId(e.target.value)}
          >
            <option value="">—</option>
            {vendors.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
        </Field>
        {!item && (
          <p className="-mt-2 text-xs text-slate-400">
            New items start at zero on hand — stock arrives through a received purchase order.
          </p>
        )}
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
