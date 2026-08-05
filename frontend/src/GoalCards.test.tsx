import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GoalCards } from "./GoalCards";
import type { Goal } from "./goals";

vi.mock("./api/client", () => ({ apiFetch: vi.fn(), API_BASE: "" }));
import { apiFetch } from "./api/client";

const goal = (over: Partial<Goal> = {}): Goal => ({
  id: "g1",
  name: "Emergency Fund",
  kind: "savings",
  target_amount: "1000.0000",
  target_date: null,
  monthly_funding: null,
  status: "active",
  account_ids: [],
  progress: "400.0000",
  projected_date: "2026-09-01",
  ...over,
});

function show() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <GoalCards />
    </QueryClientProvider>,
  );
}

beforeEach(() => vi.mocked(apiFetch).mockReset());

describe("GoalCards", () => {
  it("shows a goal's name, progress, and target", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/goals") return [goal()];
      if (path === "/accounts") return [];
      return [];
    });
    show();
    expect(await screen.findByText("Emergency Fund")).toBeInTheDocument();
    expect(screen.getByText(/\$400\.00 of \$1,000\.00/)).toBeInTheDocument();
  });

  it("shows an empty state with no goals", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => (path === "/goals" ? [] : []));
    show();
    expect(await screen.findByText("No goals yet — add one above.")).toBeInTheDocument();
  });

  it("submitting the new-goal form posts a create request", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string, opts?: RequestInit) => {
      if (path === "/goals" && opts?.method === "POST") return goal();
      if (path === "/goals") return [];
      if (path === "/accounts") return [];
      return [];
    });
    show();
    fireEvent.change(await screen.findByLabelText("Goal name"), { target: { value: "Vacation" } });
    fireEvent.change(screen.getByLabelText("Target amount"), { target: { value: "2000" } });
    fireEvent.click(screen.getByRole("button", { name: "Add goal" }));
    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith(
        "/goals",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("clicking delete removes the goal", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string, opts?: RequestInit) => {
      if (path === "/goals" && (!opts || opts.method === undefined)) return [goal()];
      if (path === "/accounts") return [];
      if (path === `/goals/${goal().id}` && opts?.method === "DELETE") return { status: "ok" };
      return [];
    });
    show();
    fireEvent.click(await screen.findByRole("button", { name: `Delete ${goal().name}` }));
    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith(`/goals/${goal().id}`, expect.objectContaining({ method: "DELETE" })),
    );
  });
});
