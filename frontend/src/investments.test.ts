import { describe, expect, it } from "vitest";
import { grossAmount, holdingTotals, isInflow, type Holding } from "./investments";

describe("grossAmount", () => {
  it("multiplies quantity by price for a buy or sell", () => {
    expect(grossAmount("12.5", "241.30")).toBe(12.5 * 241.3);
  });

  it("falls back to the bare price when quantity is unknown — a dividend logged as a total", () => {
    expect(grossAmount("0", "84.12")).toBe(84.12);
    expect(grossAmount(0, 84.12)).toBe(84.12);
  });
});

describe("isInflow", () => {
  it("buys take money out; sells and dividends bring it in", () => {
    expect(isInflow("buy")).toBe(false);
    expect(isInflow("sell")).toBe(true);
    expect(isInflow("dividend")).toBe(true);
    expect(isInflow("split")).toBe(false);
  });
});

const holding = (over: Partial<Holding>): Holding => ({
  security_id: "s1",
  symbol: "VTI",
  name: null,
  currency: "USD",
  category: null,
  units: "10",
  avg_cost: "100",
  cost_base: "1000",
  price: "110",
  priced_on: "2026-07-24",
  market_value: "1100",
  unrealized: "100",
  unrealized_pct: "10",
  dividends: "0",
  share_pct: "100",
  by_account: [],
  ...over,
});

describe("holdingTotals", () => {
  it("sums market value and cost base across holdings", () => {
    const totals = holdingTotals([
      holding({ market_value: "1100", cost_base: "1000" }),
      holding({ security_id: "s2", market_value: "500", cost_base: "600" }),
    ]);
    expect(totals.market).toBe(1600);
    expect(totals.cost).toBe(1600);
    expect(totals.unrealized).toBe(0);
  });

  it("excludes an unpriced holding's market value from the total, but still counts its cost", () => {
    const totals = holdingTotals([
      holding({ market_value: "1100", cost_base: "1000" }),
      holding({ security_id: "s2", market_value: null, cost_base: "600" }),
    ]);
    expect(totals.market).toBe(1100);
    expect(totals.cost).toBe(1600);
    expect(totals.unpriced).toBe(1);
  });

  it("guards a zero cost base rather than dividing by zero", () => {
    const totals = holdingTotals([holding({ cost_base: "0", market_value: "0" })]);
    expect(totals.unrealizedPct).toBe(0);
  });
});
