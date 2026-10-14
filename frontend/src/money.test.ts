import { describe, expect, it } from "vitest";
import { accountGroups, cumulativeSpend, flowTotals, longDate, monthTotals, monthlySeries, netWorth, pct, topMerchants, units, usd } from "./money";
import type { Account, Txn } from "./data";

const acct = (type: string, balance: string): Account => ({
  id: type + balance,
  name: type,
  type,
  institution: null,
  balance,
  currency: "USD",
  beneficiary: null,
});

const txn = (posted_at: string, amount: string, merchant_raw = "X", ignored = false): Txn => ({
  id: posted_at + amount + merchant_raw,
  posted_at,
  amount,
  merchant_raw,
  category_id: null,
  currency: "USD",
  ignored,
  tags: [],
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

  it("leaves ignored transactions out of both sides", () => {
    const t = [
      txn("2026-03-01T00:00:00Z", "2000.00"),
      txn("2026-03-02T00:00:00Z", "5000.00", "Own transfer", true),
      txn("2026-03-05T00:00:00Z", "-50.00"),
      txn("2026-03-06T00:00:00Z", "-900.00", "Sofa Barn", true),
    ];
    expect(monthTotals(t, "2026-03")).toEqual({ inflow: 2000, outflow: 50, net: 1950 });
    expect(monthlySeries(t, 1, new Date(2026, 2, 15))[0].outflow).toBe(50);
    expect(flowTotals(t)).toEqual({ inflow: 2000, outflow: 50, net: 1950 });
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

  it("leaves ignored transactions out", () => {
    const t = [
      txn("2026-01-01T00:00:00Z", "-10.00", "Cafe"),
      txn("2026-01-02T00:00:00Z", "-900.00", "Sofa Barn", true),
    ];
    expect(topMerchants(t, 5)).toEqual([{ merchant: "Cafe", total: 10 }]);
  });
});

it("formats money", () => {
  expect(usd("-9.9900")).toBe("-$9.99");
});

describe("units", () => {
  it("is not money — no symbol, and fractional shares survive", () => {
    expect(units("112.50000000")).toBe("112.5");
    expect(units("0.00012345")).toBe("0.0001");
  });

  it("groups thousands", () => {
    expect(units("12345")).toBe("12,345");
  });
});

describe("pct", () => {
  it("always carries a sign, to one decimal", () => {
    expect(pct("21.6")).toBe("+21.6%");
    expect(pct("-4.25")).toBe("-4.3%");
    expect(pct(0)).toBe("+0.0%");
  });
});

describe("longDate", () => {
  it("keeps the year, because a trade log spans them", () => {
    expect(longDate("2026-03-14")).toBe("Mar 14, 2026");
  });
});

describe("cumulativeSpend", () => {
  it("is a running total of money out, one point per day, through the day asked for", () => {
    const t = [
      txn("2026-03-01T00:00:00Z", "-10.00"),
      txn("2026-03-03T00:00:00Z", "-5.00"),
      txn("2026-03-03T00:00:00Z", "2000.00"),
      txn("2026-03-04T00:00:00Z", "-900.00", "Sofa Barn", true),
      txn("2026-03-09T00:00:00Z", "-99.00"),
      txn("2026-02-02T00:00:00Z", "-77.00"),
    ];
    expect(cumulativeSpend(t, "2026-03", 4).map((p) => p.value)).toEqual([10, 10, 15, 15]);
  });
});

describe("accountGroups", () => {
  it("rolls accounts up the way a dashboard lists them, leaving out empty groups", () => {
    const groups = accountGroups([
      acct("checking", "1000.00"),
      acct("cash", "50.00"),
      acct("savings", "4000.00"),
      acct("credit_card", "-300.00"),
    ]);
    expect(groups).toEqual([
      { key: "checking", label: "Checking", total: 1050, owed: false },
      { key: "cards", label: "Card balance", total: 300, owed: true },
      { key: "net_cash", label: "Net cash", total: 4750, owed: false },
      { key: "savings", label: "Savings", total: 4000, owed: false },
    ]);
  });

  it("is empty with no accounts", () => {
    expect(accountGroups([])).toEqual([]);
  });
});
