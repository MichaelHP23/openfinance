import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./api/client";

/**
 * Types for `/investments/*` (Phase 1 of the trade-log spec).
 *
 * Decimals cross the wire as JSON strings — the backend serialises `Decimal`, never
 * `float` — so every quantity is `string | number` and `money.ts` accepts both.
 */
type Num = string | number;

export const TRADE_TYPES = ["buy", "sell", "dividend", "split"] as const;
export type TradeType = (typeof TRADE_TYPES)[number];

export type Security = {
  id: string;
  symbol: string;
  name: string | null;
  currency?: string;
  is_manual_price?: boolean;
};

export type Holding = {
  security_id: string;
  symbol: string;
  name: string | null;
  currency: string;
  category: string | null;
  units: Num;
  avg_cost: Num;
  cost_base: Num;
  /** Null when no price is known — never substitute cost base. */
  price: Num | null;
  priced_on: string | null;
  market_value: Num | null;
  unrealized: Num;
  unrealized_pct: Num;
  dividends: Num;
  share_pct: Num;
  by_account: { account_id: string; name: string; units: Num }[];
};

export type HoldingsResponse = {
  holdings: Holding[];
  /** Oldest `priced_on` across priced holdings; null when nothing is priced. */
  priced_through: string | null;
  // ponytail: the spec's response also carries a `totals` object, but Phase 1
  // never pins down its shape. `holdingTotals()` below recomputes the same
  // numbers from `holdings` — cheap, and it means this type doesn't have to
  // guess at a field neither side of the API contract has nailed down yet.
};

export type Trade = {
  id: string;
  account_id: string;
  security_id: string;
  symbol?: string;
  traded_on: string;
  type: TradeType;
  quantity: Num;
  price_per_unit: Num;
  fees: Num;
  split_ratio: Num | null;
  currency: string;
  notes: string | null;
};

export type TradesResponse = { trades: Trade[]; total: number };

export type TradeFilters = {
  security_id?: string;
  account_id?: string;
  from?: string;
  to?: string;
};

export function useSecurities() {
  return useQuery({
    queryKey: ["securities"],
    queryFn: () => apiFetch<Security[]>("/investments/securities"),
  });
}

export function useHoldings() {
  return useQuery({
    queryKey: ["holdings"],
    queryFn: () => apiFetch<HoldingsResponse>("/investments/holdings"),
  });
}

export function useTrades(filters: TradeFilters = {}) {
  const qs = new URLSearchParams(
    Object.entries(filters).filter(([, v]) => v) as [string, string][],
  ).toString();
  return useQuery({
    queryKey: ["trades", filters],
    queryFn: () => apiFetch<TradesResponse>(`/investments/trades${qs ? `?${qs}` : ""}`),
  });
}

/**
 * Cash the trade moved, before fees. A dividend may be logged either per-unit
 * (quantity × price) or as a bare total in `price_per_unit` with no units — see the
 * `Trade` model note in the spec. A split moves no cash and lands on 0.
 */
export const grossAmount = (quantity: Num, price: Num) =>
  Number(quantity) ? Number(quantity) * Number(price) : Number(price);

/** Buys take money out; sells and dividends bring it in. Drives sign and tone. */
export const isInflow = (type: TradeType) => type === "sell" || type === "dividend";

/** Sum the priced rows only — an unpriced holding is reported, never guessed at. */
export function holdingTotals(holdings: Holding[]) {
  let market = 0;
  let cost = 0;
  let unpriced = 0;
  for (const h of holdings) {
    cost += Number(h.cost_base);
    if (h.market_value === null) unpriced += 1;
    else market += Number(h.market_value);
  }
  const unrealized = market - cost;
  return {
    market,
    cost,
    unrealized,
    unrealizedPct: cost ? (unrealized / cost) * 100 : 0,
    unpriced,
  };
}

/** Body of `POST /investments/trades` — see spec §7 Phase 1, `TradeIn`. */
export type TradeIn = {
  account_id: string;
  symbol: string;
  traded_on: string;
  type: TradeType;
  quantity: string;
  price_per_unit: string;
  fees: string;
  split_ratio: string | null;
  currency: string;
  notes: string | null;
};

/** Refetch everything a trade write can change: the log itself, derived
 *  holdings, and — because an unrecognised symbol creates a security —
 *  the securities list the trade form's datalist reads from. */
function invalidateTradeEffects(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["trades"] });
  qc.invalidateQueries({ queryKey: ["holdings"] });
  qc.invalidateQueries({ queryKey: ["securities"] });
}

export function useCreateTrade() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: TradeIn) =>
      apiFetch<Trade>("/investments/trades", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => invalidateTradeEffects(qc),
  });
}

export function useDeleteTrade() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(`/investments/trades/${id}`, { method: "DELETE" }),
    onSuccess: () => invalidateTradeEffects(qc),
  });
}

/** Body of `POST /investments/prices` — a manual close for one security/day. */
export type PriceOverride = { security_id: string; priced_on: string; close: string };

export function useSetPrice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: PriceOverride) =>
      apiFetch("/investments/prices", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["holdings"] }),
  });
}

/** Shape of `POST /investments/trades/import`'s response — spec §8.4 `TradeImportResult`. */
export type TradeImportResult = {
  imported: number;
  skipped: number;
  errors: [row: number, reason: string][];
};
