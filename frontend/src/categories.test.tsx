import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useCategoryMap } from "./categories";

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
