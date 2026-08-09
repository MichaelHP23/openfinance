import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { SpendingCard, YearInReviewCard, TaxCard } from "./ReportsCards";

vi.mock("./api/client", () => ({ apiFetch: vi.fn(), API_BASE: "" }));
import { apiFetch } from "./api/client";

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => vi.mocked(apiFetch).mockReset());

describe("SpendingCard", () => {
  it("renders a bar per bucket, biggest first", async () => {
    vi.mocked(apiFetch).mockResolvedValue([
      { key: "Groceries", key_id: "c1", total: "50.00", count: 2 },
      { key: "Coffee", key_id: "c2", total: "5.00", count: 1 },
    ]);
    render(<SpendingCard start="2026-07-01" end="2026-07-31" groupBy="category" />, { wrapper });
    await screen.findByText("Groceries");
    expect(screen.getByText("Coffee")).toBeInTheDocument();
  });

  it("shows an empty state when there is nothing to report", async () => {
    vi.mocked(apiFetch).mockResolvedValue([]);
    render(<SpendingCard start="2026-07-01" end="2026-07-31" groupBy="category" />, { wrapper });
    await waitFor(() => expect(screen.getByText(/nothing to report/i)).toBeInTheDocument());
  });
});

describe("YearInReviewCard", () => {
  it("shows the year's totals and biggest category", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      year: 2026,
      total_in: "3000.00",
      total_out: "550.00",
      savings_rate: "81.7",
      biggest_category: "Electronics",
      biggest_category_amount: "500.00",
      biggest_transaction_merchant: "APPLE STORE",
      biggest_transaction_amount: "500.00",
      new_subscriptions: ["Netflix"],
      cancelled_subscriptions: ["Gym"],
      net_worth_delta: "1200.00",
    });
    render(<YearInReviewCard year={2026} />, { wrapper });
    await screen.findByText("Electronics");
    expect(screen.getByText("Netflix")).toBeInTheDocument();
    expect(screen.getByText("Gym")).toBeInTheDocument();
  });
});

describe("TaxCard", () => {
  it("shows the wash-sale disclaimer and never the word advice", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path?.startsWith("/tax/realized-gains")) {
        return { year: 2026, gains: [], short_term_gain: "0", long_term_gain: "0", total_gain: "0" };
      }
      if (path?.startsWith("/tax/income-summary")) {
        return { year: 2026, dividends: "0", interest: "0", total: "0" };
      }
      return undefined;
    });
    render(<TaxCard year={2026} />, { wrapper });
    await screen.findByText(/wash sale/i);
    expect(screen.queryByText(/advice/i)).not.toBeInTheDocument();
  });
});
