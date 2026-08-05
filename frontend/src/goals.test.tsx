import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { goalPercent, useGoals } from "./goals";
import type { Goal } from "./goals";

vi.mock("./api/client", () => ({ apiFetch: vi.fn(), API_BASE: "" }));
import { apiFetch } from "./api/client";

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => vi.mocked(apiFetch).mockReset());

const goal = (over: Partial<Goal> = {}): Goal => ({
  id: "g1",
  name: "Fund",
  kind: "savings",
  target_amount: "1000.0000",
  target_date: null,
  monthly_funding: null,
  status: "active",
  account_ids: [],
  progress: "250.0000",
  projected_date: null,
  ...over,
});

describe("useGoals", () => {
  it("fetches the goal list", async () => {
    vi.mocked(apiFetch).mockResolvedValue([goal()]);
    const { result } = renderHook(() => useGoals(), { wrapper });
    await waitFor(() => expect(result.current.data?.[0].name).toBe("Fund"));
    expect(apiFetch).toHaveBeenCalledWith("/goals");
  });
});

describe("goalPercent", () => {
  it("is progress over target, as a percentage", () => {
    expect(goalPercent(goal({ progress: "250.0000", target_amount: "1000.0000" }))).toBe(25);
  });

  it("clamps below zero up to zero", () => {
    expect(goalPercent(goal({ progress: "-50.0000" }))).toBe(0);
  });

  it("clamps above 100 down to 100", () => {
    expect(goalPercent(goal({ progress: "1500.0000", target_amount: "1000.0000" }))).toBe(100);
  });

  it("is zero for a zero or negative target rather than dividing by it", () => {
    expect(goalPercent(goal({ target_amount: "0" }))).toBe(0);
  });
});
