import { describe, expect, it } from "vitest";
import { firstNegativeDay } from "./forecast";
import type { ForecastDay } from "./forecast";

const day = (on: string, balance: string): ForecastDay => ({
  on, projected_balance: balance, contributions: [],
});

describe("firstNegativeDay", () => {
  it("finds the first day the balance drops below zero", () => {
    const days = [day("2026-07-01", "500.00"), day("2026-07-02", "-10.00"), day("2026-07-03", "-20.00")];
    expect(firstNegativeDay(days)?.on).toBe("2026-07-02");
  });

  it("is null when the balance never goes negative", () => {
    expect(firstNegativeDay([day("2026-07-01", "500.00")])).toBeNull();
  });
});
