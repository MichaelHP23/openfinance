import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ForecastChart } from "./ForecastChart";
import type { ForecastDay } from "./forecast";

vi.mock("./api/client", () => ({ apiFetch: vi.fn(), API_BASE: "" }));
import { apiFetch } from "./api/client";

const days = (): ForecastDay[] => [
  { on: "2026-07-01", projected_balance: "1000.00", contributions: [] },
  { on: "2026-07-02", projected_balance: "900.00", contributions: [] },
  { on: "2026-07-03", projected_balance: "-50.00", contributions: ["Rent -950.00"] },
];

function show() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <ForecastChart />
    </QueryClientProvider>,
  );
}

beforeEach(() => vi.mocked(apiFetch).mockReset());

describe("ForecastChart", () => {
  it("shows a negative-balance marker when the forecast dips below zero", async () => {
    // Both ternary branches return the same value; the guard is dropped rather than made
    // `path && path.startsWith(...)` because plain `days()` says the same thing without
    // implying a branch that never diverges. (An unrelated call the harness makes with an
    // undefined path during teardown — also tolerated by GoalCards.test.tsx's `===` checks
    // — would otherwise crash a `.startsWith` on it.)
    vi.mocked(apiFetch).mockImplementation(async () => days());
    show();
    expect(await screen.findByText(/Projected to go negative on 2026-07-03/)).toBeInTheDocument();
  });

  it("shows no marker when the forecast never goes negative", async () => {
    vi.mocked(apiFetch).mockResolvedValue([
      { on: "2026-07-01", projected_balance: "1000.00", contributions: [] },
      { on: "2026-07-02", projected_balance: "900.00", contributions: [] },
    ]);
    show();
    await waitFor(() => expect(apiFetch).toHaveBeenCalled());
    expect(screen.queryByText(/Projected to go negative/)).not.toBeInTheDocument();
  });

  it("submitting the can-I-afford form posts to /forecast/afford and shows the verdict", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string, opts?: RequestInit) => {
      if (path === "/forecast/afford" && opts?.method === "POST") {
        return {
          baseline: days(), with_amount: days(), stays_non_negative: true,
          minimum_balance: "50.00", goal_impact: [],
        };
      }
      return days();
    });
    show();
    // A few days out from whatever "today" actually is — the Date input now has a
    // `min` of today, so a hardcoded past date would fail native validation and
    // silently block the submit.
    const soon = new Date(Date.now() + 5 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
    fireEvent.change(await screen.findByLabelText("Amount"), { target: { value: "500" } });
    fireEvent.change(screen.getByLabelText("Date"), { target: { value: soon } });
    fireEvent.click(screen.getByRole("button", { name: "Check" }));
    expect(await screen.findByText(/stays at \$50\.00/)).toBeInTheDocument();
  });
});
