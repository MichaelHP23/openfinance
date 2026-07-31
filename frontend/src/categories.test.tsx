import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useCategoryMap } from "./categories";
// Not "./categories" — that bare specifier resolves to categories.ts (Vite prefers
// .ts over .tsx), so the component lives in its own file. See CategoryPicker.tsx.
import { CategoryPicker } from "./CategoryPicker";
import { RulesCard } from "./CategoryCards";

vi.mock("./api/client", () => ({ apiFetch: vi.fn(), API_BASE: "" }));
import { apiFetch } from "./api/client";

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => vi.mocked(apiFetch).mockReset());

describe("useCategoryMap", () => {
  it("labels a leaf with its group", async () => {
    vi.mocked(apiFetch).mockResolvedValue([
      { id: "g1", name: "Food & Drink", parent_id: null, is_system: true },
      { id: "c1", name: "Groceries", parent_id: "g1", is_system: true },
    ]);
    const { result } = renderHook(() => useCategoryMap(), { wrapper });
    await waitFor(() => expect(result.current.get("c1")).toBe("Food & Drink · Groceries"));
  });

  it("labels a top-level category with just its name", async () => {
    vi.mocked(apiFetch).mockResolvedValue([
      { id: "g1", name: "Transfers", parent_id: null, is_system: true },
    ]);
    const { result } = renderHook(() => useCategoryMap(), { wrapper });
    await waitFor(() => expect(result.current.get("g1")).toBe("Transfers"));
  });
});

describe("CategoryPicker", () => {
  it("groups leaves under their parent and reports the chosen id", async () => {
    vi.mocked(apiFetch).mockResolvedValue([
      { id: "g1", name: "Food & Drink", parent_id: null, is_system: true },
      { id: "c1", name: "Groceries", parent_id: "g1", is_system: true },
    ]);
    const onChange = vi.fn();
    render(<CategoryPicker value={null} onChange={onChange} ariaLabel="Category" />, {
      wrapper,
    });
    const select = await screen.findByLabelText("Category");
    // The <select> exists from the first render, before the category fetch settles —
    // wait for the leaf option itself so the change below targets a real <option>.
    await screen.findByRole("option", { name: "Groceries" });
    fireEvent.change(select, { target: { value: "c1" } });
    expect(onChange).toHaveBeenCalledWith("c1");
  });
});

describe("RulesCard", () => {
  it("lists rules in priority order with their category label", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/categories")
        return [
          { id: "g1", name: "Food & Drink", parent_id: null, is_system: true },
          { id: "c1", name: "Groceries", parent_id: "g1", is_system: true },
        ];
      if (path === "/category-rules")
        return [
          {
            id: "r1",
            match_type: "merchant_contains",
            pattern: "whole foods",
            category_id: "c1",
            min_amount: null,
            max_amount: null,
            account_id: null,
            priority: 10,
            source: "user",
          },
        ];
      return [];
    });
    render(<RulesCard />, { wrapper });
    expect(await screen.findByText("whole foods")).toBeInTheDocument();
    expect(await screen.findByText("Food & Drink · Groceries")).toBeInTheDocument();
  });

  it("shows an empty state when there are no rules", async () => {
    vi.mocked(apiFetch).mockResolvedValue([]);
    render(<RulesCard />, { wrapper });
    expect(await screen.findByText(/No rules yet/i)).toBeInTheDocument();
  });
});
