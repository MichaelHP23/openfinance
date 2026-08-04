import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { shiftMonth, useBudgetStatus } from "./budgets";

vi.mock("./api/client", () => ({ apiFetch: vi.fn(), API_BASE: "" }));
import { apiFetch } from "./api/client";

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => vi.mocked(apiFetch).mockReset());

describe("shiftMonth", () => {
  it("moves forward across a year boundary", () => {
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
  });

  it("moves backward across a year boundary", () => {
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
  });

  it("moves within a year", () => {
    expect(shiftMonth("2026-07", 1)).toBe("2026-08");
  });
});

describe("useBudgetStatus", () => {
  it("fetches the given month's status", async () => {
    vi.mocked(apiFetch).mockResolvedValue([
      {
        category_id: "c1",
        category_name: "Groceries",
        budgeted: "300.0000",
        carry_in: "0.0000",
        effective_budget: "300.0000",
        actual: "40.0000",
        remaining: "260.0000",
        pace: 0.2,
        rollover: false,
      },
    ]);
    const { result } = renderHook(() => useBudgetStatus("2026-07"), { wrapper });
    await waitFor(() => expect(result.current.data?.[0].category_name).toBe("Groceries"));
    expect(apiFetch).toHaveBeenCalledWith("/budgets/2026-07");
  });
});
