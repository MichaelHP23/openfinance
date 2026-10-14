import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, test, vi } from "vitest";
import { OverviewPage } from "./OverviewPage";

vi.mock("../api/client", () => ({ apiFetch: vi.fn(), API_BASE: "" }));
import { apiFetch } from "../api/client";

// The page reads "this month" off the clock, so the fixtures are dated off it too.
const now = new Date();
const month = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
const txn = (id: string, amount: string, merchant_raw: string, ignored = false) => ({
  id,
  posted_at: `${month}-01T00:00:00Z`,
  merchant_raw,
  amount,
  currency: "USD",
  category_id: null,
  ignored,
  tags: [],
});
const account = (type: string, balance: string) => ({
  id: type,
  name: type,
  type,
  institution: null,
  balance,
  currency: "USD",
  beneficiary: null,
});

function api(over: Record<string, unknown> = {}) {
  const data: Record<string, unknown> = {
    "/accounts": [account("checking", "1000.00"), account("credit_card", "-300.00")],
    "/transactions": [
      txn("1", "-42.50", "Whole Foods"),
      txn("2", "-900.00", "Sofa Barn", true),
      txn("3", "3200.00", "Acme Payroll"),
    ],
    "/recurring/summary": {
      monthly_committed: "15.99",
      monthly_incoming: "0",
      active_count: 1,
      upcoming: [{ id: "s1", label: "Netflix", on: `${month}-28`, amount: "-15.99" }],
      price_increases: 0,
      last_detected_at: null,
    },
    "/forecast/safe-to-spend": { amount: "640.00", until: null, bills_due: 1 },
    "/insights/available": { available: false },
    ...over,
  };
  vi.mocked(apiFetch).mockImplementation(async (path: string) => {
    if (path in data) return data[path];
    return [];
  });
}

const show = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <OverviewPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

test("leads with this month's spend, leaving ignored transactions out of it", async () => {
  api();
  show();
  const hero = (await screen.findByText("Current spend this month")).closest("section")!;
  expect(await within(hero).findByText("$42.50")).toBeInTheDocument();
});

test("lists accounts rolled up by kind, with what the cards are owed", async () => {
  api();
  show();
  const card = (await screen.findByRole("heading", { name: "Accounts" })).closest("section")!;
  expect(await within(card).findByText("Checking")).toBeInTheDocument();
  expect(within(card).getByText("Card balance")).toBeInTheDocument();
  expect(within(card).getByText("$300.00")).toBeInTheDocument();
  expect(within(card).getByText("Net cash")).toBeInTheDocument();
});

test("shows the bills coming up", async () => {
  api();
  show();
  const card = (await screen.findByRole("heading", { name: "Upcoming" })).closest("section")!;
  expect(await within(card).findByText("Netflix")).toBeInTheDocument();
  expect(within(card).getByText("$15.99")).toBeInTheDocument();
});

test("recent activity marks an ignored transaction instead of hiding it", async () => {
  api();
  show();
  const card = (await screen.findByRole("heading", { name: "Recent activity" })).closest("section")!;
  expect(await within(card).findByText("Sofa Barn")).toBeInTheDocument();
  expect(within(card).getByText(/Ignored/)).toBeInTheDocument();
  expect(within(card).getByText("+$3,200.00")).toBeInTheDocument();
});

test("an empty install is invited to add an account, not shown a wall of zeros", async () => {
  api({ "/accounts": [], "/transactions": [] });
  show();
  expect(await screen.findByRole("link", { name: "Add your first account" })).toHaveAttribute(
    "href",
    "/accounts",
  );
  expect(screen.queryByText("Current spend this month")).not.toBeInTheDocument();
});
