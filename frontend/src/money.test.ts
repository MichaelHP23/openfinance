import { describe, expect, it } from "vitest";
import { monthTotals, monthlySeries, netWorth, topMerchants, usd } from "./money";
import type { Account, Txn } from "./data";

const acct = (type: string, balance: string): Account => ({
  id: type + balance,
  name: type,
  type,
  institution: null,
  balance,
  currency: "USD",
});

const txn = (posted_at: string, amount: string, merchant_raw = "X"): Txn => ({
  id: posted_at + amount + merchant_raw,
  posted_at,
  amount,
  merchant_raw,
  currency: "USD",
});

describe("netWorth", () => {
  it("subtracts liabilities from assets", () => {
    const { assets, debts, net } = netWorth([
      acct("checking", "1000.00"),
      acct("savings", "500.00"),
      acct("credit_card", "300.00"),
    ]);
    expect(assets).toBe(1500);
    expect(debts).toBe(300);
    expect(net).toBe(1200);
  });

  it("counts a liability as debt even when its balance is entered negative", () => {
    expect(netWorth([acct("loan", "-2000.00")]).net).toBe(-2000);
  });
});

describe("monthTotals", () => {
  it("splits inflow from outflow for one month only", () => {
    const t = [
      txn("2026-03-01T00:00:00Z", "2000.00"),
      txn("2026-03-05T00:00:00Z", "-50.00"),
      txn("2026-02-01T00:00:00Z", "-999.00"),
    ];
    expect(monthTotals(t, "2026-03")).toEqual({ inflow: 2000, outflow: 50, net: 1950 });
  });
});

describe("monthlySeries", () => {
  it("returns the requested months oldest first, spanning a year boundary", () => {
    const series = monthlySeries([txn("2025-12-10T00:00:00Z", "-25.00")], 3, new Date(2026, 1, 15));
    expect(series.map((m) => m.key)).toEqual(["2025-12", "2026-01", "2026-02"]);
    expect(series[0].outflow).toBe(25);
  });
});

describe("topMerchants", () => {
  it("sums spend per merchant and ignores income", () => {
    const t = [
      txn("2026-01-01T00:00:00Z", "-10.00", "Cafe"),
      txn("2026-01-02T00:00:00Z", "-5.00", "Cafe"),
      txn("2026-01-03T00:00:00Z", "-12.00", "Store"),
      txn("2026-01-04T00:00:00Z", "3000.00", "Payroll"),
    ];
    expect(topMerchants(t, 2)).toEqual([
      { merchant: "Cafe", total: 15 },
      { merchant: "Store", total: 12 },
    ]);
  });
});

it("formats money", () => {
  expect(usd("-9.9900")).toBe("-$9.99");
});
