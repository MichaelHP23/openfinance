import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { expect, test, vi } from "vitest";
import { TransactionList } from "./transactions";

vi.mock("./api/client", () => ({
  API_BASE: "",
  apiFetch: vi.fn(async () => [
    {
      id: "1",
      posted_at: "2026-01-01T12:00:00Z",
      merchant_raw: "Starbucks",
      amount: "-9.99",
      currency: "USD",
    },
    {
      id: "2",
      posted_at: "2026-01-02T12:00:00Z",
      merchant_raw: "Payroll",
      amount: "2500.00",
      currency: "USD",
    },
  ]),
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
