import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useCategoryMap } from "./categories";
// Not "./categories" — that bare specifier resolves to categories.ts (Vite prefers
// .ts over .tsx), so the component lives in its own file. See CategoryPicker.tsx.
import { CategoryPicker } from "./CategoryPicker";
import { RulesCard, UncategorizedCard } from "./CategoryCards";

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

  const twoRules = [
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
    {
      id: "r2",
      match_type: "merchant_contains",
      pattern: "trader joe's",
      category_id: "c1",
      min_amount: null,
      max_amount: null,
      account_id: null,
      priority: 20,
      source: "user",
    },
  ];

  it("disables move buttons while a reorder is in flight, so a second click can't race the first", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/categories") return [];
      if (path === "/category-rules") return twoRules;
      if (path === "/category-rules/reorder") return new Promise(() => {}); // never resolves
      return [];
    });
    render(<RulesCard />, { wrapper });
    const upButtons = await screen.findAllByLabelText(/Move .* up/);
    fireEvent.click(upButtons[1]);
    await waitFor(() => expect(upButtons[1]).toBeDisabled());
  });

  it("shows an error when deleting a rule fails", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string, opts?: RequestInit) => {
      if (path === "/categories") return [];
      if (path === "/category-rules") return twoRules;
      if (path === "/category-rules/r1" && opts?.method === "DELETE")
        throw new Error("Rule not found");
      return [];
    });
    render(<RulesCard />, { wrapper });
    fireEvent.click(await screen.findByLabelText("Delete whole foods"));
    expect(await screen.findByText("Rule not found")).toBeInTheDocument();
  });

  it("shows an error when 'Apply to history' fails", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/categories") return [];
      if (path === "/category-rules") return [];
      if (path === "/categorization/backfill") throw new Error("Backfill failed");
      return [];
    });
    render(<RulesCard />, { wrapper });
    fireEvent.click(await screen.findByText("Apply to history"));
    expect(await screen.findByText("Backfill failed")).toBeInTheDocument();
  });
});

describe("UncategorizedCard", () => {
  it("shows how many uncategorized merchants are hidden past the cap", async () => {
    const rows = Array.from({ length: 20 }, (_, i) => ({
      merchant: `Merchant ${i}`,
      count: 1,
      total: "1.00",
      currency: "USD",
    }));
    vi.mocked(apiFetch).mockImplementation(async (path: string) =>
      path === "/categorization/uncategorized" ? rows : [],
    );
    render(<UncategorizedCard />, { wrapper });
    expect(await screen.findByText(/5 more/)).toBeInTheDocument();
  });

  it("renders a non-USD total with its currency code instead of formatting it as USD", async () => {
    const rows = [{ merchant: "Foo", count: 2, total: "10.00", currency: "EUR" }];
    vi.mocked(apiFetch).mockImplementation(async (path: string) =>
      path === "/categorization/uncategorized" ? rows : [],
    );
    render(<UncategorizedCard />, { wrapper });
    expect(await screen.findByText("10.00 EUR")).toBeInTheDocument();
    expect(screen.queryByText("$10.00")).not.toBeInTheDocument();
  });

  it("renders the same merchant twice when it appears in two currencies", async () => {
    const rows = [
      { merchant: "Foo", count: 1, total: "5.00", currency: "USD" },
      { merchant: "Foo", count: 1, total: "5.00", currency: "EUR" },
    ];
    vi.mocked(apiFetch).mockImplementation(async (path: string) =>
      path === "/categorization/uncategorized" ? rows : [],
    );
    render(<UncategorizedCard />, { wrapper });
    expect(await screen.findByText("$5.00")).toBeInTheDocument();
    expect(await screen.findByText("5.00 EUR")).toBeInTheDocument();
  });
});
