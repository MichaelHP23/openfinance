import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BudgetBoard } from "./BudgetBoard";
import type { BudgetStatus } from "./budgets";

vi.mock("./api/client", () => ({ apiFetch: vi.fn(), API_BASE: "" }));
import { apiFetch } from "./api/client";

const row = (over: Partial<BudgetStatus> = {}): BudgetStatus => ({
  category_id: "c1",
  category_name: "Groceries",
  budgeted: "100.0000",
  carry_in: "0.0000",
  effective_budget: "100.0000",
  actual: "40.0000",
  remaining: "60.0000",
  pace: 0.5,
  rollover: false,
  ...over,
});

function show(month = "2026-07") {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <BudgetBoard month={month} onMonthChange={() => {}} />
    </QueryClientProvider>,
  );
}

beforeEach(() => vi.mocked(apiFetch).mockReset());

describe("BudgetBoard", () => {
  it("shows the category name, actual, and remaining", async () => {
    vi.mocked(apiFetch).mockResolvedValue([row()]);
    show();
    expect(await screen.findByText("Groceries")).toBeInTheDocument();
    expect(screen.getByText("$40.00")).toBeInTheDocument();
    expect(screen.getByText("$60.00")).toBeInTheDocument();
  });

  it("filling in an amount and saving PUTs the new budget", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string, opts?: RequestInit) => {
      if (path === "/budgets/2026-07" && opts?.method === "PUT") return [];
      return [row()];
    });
    show();
    const input = await screen.findByLabelText("Budget for Groceries");
    fireEvent.change(input, { target: { value: "150" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith(
        "/budgets/2026-07",
        expect.objectContaining({ method: "PUT" }),
      ),
    );
  });

  it("has no save button when nothing has been edited", async () => {
    vi.mocked(apiFetch).mockResolvedValue([row()]);
    show();
    await screen.findByText("Groceries");
    expect(screen.queryByRole("button", { name: "Save changes" })).not.toBeInTheDocument();
  });

  it("disables save when the only edit is a blanked-out input", async () => {
    vi.mocked(apiFetch).mockResolvedValue([row()]);
    show();
    const input = await screen.findByLabelText("Budget for Groceries");
    fireEvent.change(input, { target: { value: "" } });
    const saveButton = await screen.findByRole("button", { name: "Save changes" });
    expect(saveButton).toBeDisabled();
    fireEvent.click(saveButton);
    // A disabled button doesn't fire onClick, so no PUT should ever go out.
    expect(apiFetch).not.toHaveBeenCalledWith(
      "/budgets/2026-07",
      expect.objectContaining({ method: "PUT" }),
    );
  });
});
