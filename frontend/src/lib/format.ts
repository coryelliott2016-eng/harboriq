/** Display formatting helpers.
 *
 * Moved out of components/ui.tsx so that file only exports components —
 * required for Vite React fast refresh (react-refresh/only-export-components).
 */

export function money(value: string | number): string {
  const n = typeof value === "string" ? parseFloat(value) : value;
  if (Number.isNaN(n)) return "$0.00";
  return n.toLocaleString(undefined, { style: "currency", currency: "USD" });
}

export function customerName(c: { first_name: string | null; last_name: string | null; company_name: string | null }): string {
  if (c.company_name) return c.company_name;
  const name = [c.first_name, c.last_name].filter(Boolean).join(" ");
  return name || "Unnamed customer";
}
