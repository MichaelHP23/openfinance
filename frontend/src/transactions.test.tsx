import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { expect, test, vi } from "vitest";
import { TransactionList } from "./transactions";

vi.mock("./api/client", () => ({
  API_BASE: "",
  apiFetch: vi.fn(async () => [
    {
      id: "1",
      posted_at: "2026-01-01T00:00:00Z",
      merchant_raw: "Starbucks",
      amount: "-9.99",
      currency: "USD",
    },
  ]),
}));

test("renders a transaction row", async () => {
  const qc = new QueryClient();
  render(
    <QueryClientProvider client={qc}>
      <TransactionList />
    </QueryClientProvider>,
  );
  expect(await screen.findByText("Starbucks")).toBeInTheDocument();
  expect(screen.getByText("2026-01-01")).toBeInTheDocument();
});
