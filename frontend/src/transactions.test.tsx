import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { expect, test, vi } from "vitest";
import { TransactionList } from "./transactions";

vi.mock("./api/client", () => ({
  API_BASE: "",
  // TxnRows now renders a CategoryPicker per row, which calls useCategories — give it
  // an empty taxonomy so it doesn't fall through to the transactions fixture below.
  apiFetch: vi.fn(async (path: string) =>
    path.startsWith("/categories")
      ? []
      : [
          {
            id: "1",
            posted_at: "2026-01-01T12:00:00Z",
            merchant_raw: "Starbucks",
            amount: "-9.99",
            currency: "USD",
            category_id: null,
          },
          {
            id: "2",
            posted_at: "2026-01-02T12:00:00Z",
            merchant_raw: "Payroll",
            amount: "2500.00",
            currency: "USD",
            category_id: null,
          },
        ],
  ),
}));

const renderList = () =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <TransactionList />
    </QueryClientProvider>,
  );

test("renders transactions with a short date", async () => {
  renderList();
  expect(await screen.findByText("Starbucks")).toBeInTheDocument();
  expect(screen.getByText("Jan 1")).toBeInTheDocument();
});

test("signs amounts: outflow bare, inflow with a plus", async () => {
  renderList();
  expect(await screen.findByText("-$9.99")).toBeInTheDocument();
  expect(screen.getByText("+$2,500.00")).toBeInTheDocument();
});
