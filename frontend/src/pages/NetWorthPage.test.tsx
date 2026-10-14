import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, test, vi } from "vitest";
import { NetWorthPage } from "./NetWorthPage";

vi.mock("../api/client", () => ({ apiFetch: vi.fn(), API_BASE: "" }));
import { apiFetch } from "../api/client";

const account = (id: string, type: string, name: string, balance: string) => ({
  id,
  name,
  type,
  institution: null,
  balance,
  currency: "USD",
  beneficiary: null,
});

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
  vi.mocked(apiFetch).mockImplementation(async (path: string) => {
    if (path === "/accounts")
      return [
        account("a1", "checking", "Everyday Checking", "1000.00"),
        account("a2", "investment", "Brokerage", "4000.00"),
        account("a3", "credit_card", "Rewards Card", "-300.00"),
        account("a4", "loan", "Car Loan", "-2000.00"),
      ];
    return [
      { on: "2026-10-01", assets: 4800, debts: 2400, net: 2400 },
      { on: "2026-10-13", assets: 5000, debts: 2300, net: 2700 },
    ];
  });
});

const show = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <NetWorthPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );

test("Summary leads with net worth and both sides of it", async () => {
  show();
  const summary = await screen.findByRole("tabpanel", { name: "Summary" });
  expect(await within(summary).findByText("$2,700.00")).toBeInTheDocument();
  expect(within(summary).getByText("$5,000.00")).toBeInTheDocument();
  expect(within(summary).getByText("$2,300.00")).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Summary" })).toHaveAttribute("aria-selected", "true");
});

test("Assets lists what is owned and nothing that is owed", async () => {
  show();
  fireEvent.click(await screen.findByRole("tab", { name: "Assets" }));
  const panel = screen.getByRole("tabpanel", { name: "Assets" });
  expect(await within(panel).findByRole("link", { name: /Everyday Checking/ })).toHaveAttribute(
    "href",
    "/accounts/a1",
  );
  expect(within(panel).getByText("Brokerage")).toBeInTheDocument();
  expect(within(panel).queryByText("Rewards Card")).not.toBeInTheDocument();
});

test("Debts lists what is owed, as positive amounts", async () => {
  show();
  fireEvent.click(await screen.findByRole("tab", { name: "Debts" }));
  const panel = screen.getByRole("tabpanel", { name: "Debts" });
  expect(await within(panel).findByText("Car Loan")).toBeInTheDocument();
  expect(within(panel).getByText("$2,000.00")).toBeInTheDocument();
  expect(within(panel).getByText("Rewards Card")).toBeInTheDocument();
  expect(within(panel).queryByText("Brokerage")).not.toBeInTheDocument();
});
