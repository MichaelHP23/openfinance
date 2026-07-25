import type { Account, Txn } from "./data";

// ponytail: Number() for presentation only. Amounts stay strings end to end; the
// backend is the only thing that does arithmetic that has to be exact.
const num = (v: string | number) => Number(v);

const fmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const compact = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  notation: "compact",
  maximumFractionDigits: 1,
});

export const usd = (v: string | number) => fmt.format(num(v));
export const usdCompact = (v: string | number) => compact.format(num(v));

export const signed = (v: string | number) => (num(v) > 0 ? `+${usd(v)}` : usd(v));

export const LIABILITY_TYPES = new Set(["credit_card", "loan", "liability"]);

export function netWorth(accounts: Account[]) {
  let assets = 0;
  let debts = 0;
  for (const a of accounts) {
    const bal = num(a.balance);
    if (LIABILITY_TYPES.has(a.type)) debts += Math.abs(bal);
    else assets += bal;
  }
  return { assets, debts, net: assets - debts };
}

const monthKey = (iso: string) => iso.slice(0, 7);

export function monthTotals(txns: Txn[], key: string) {
  let inflow = 0;
  let outflow = 0;
  for (const t of txns) {
    if (monthKey(t.posted_at) !== key) continue;
    const amt = num(t.amount);
    if (amt >= 0) inflow += amt;
    else outflow += -amt;
  }
  return { inflow, outflow, net: inflow - outflow };
}

/** Last `count` months, oldest first, as {key, label, inflow, outflow}. */
export function monthlySeries(txns: Txn[], count: number, today: Date) {
  const months: { key: string; label: string; inflow: number; outflow: number }[] = [];
  for (let i = count - 1; i >= 0; i--) {
    const d = new Date(today.getFullYear(), today.getMonth() - i, 1);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    months.push({
      key,
      label: d.toLocaleString("en-US", { month: "short" }),
      ...monthTotals(txns, key),
    });
  }
  return months;
}

export function topMerchants(txns: Txn[], limit: number) {
  const totals = new Map<string, number>();
  for (const t of txns) {
    const amt = num(t.amount);
    if (amt >= 0) continue;
    totals.set(t.merchant_raw, (totals.get(t.merchant_raw) ?? 0) + -amt);
  }
  return [...totals.entries()]
    .map(([merchant, total]) => ({ merchant, total }))
    .sort((a, b) => b.total - a.total)
    .slice(0, limit);
}

export const prettyType = (t: string) => t.replace(/_/g, " ");

// Posted dates are stored at UTC midnight, so render them in UTC — otherwise a
// negative-offset timezone shows every transaction one day early.
export const shortDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
