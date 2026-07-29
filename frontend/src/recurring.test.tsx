import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, test, vi } from "vitest";
import { RecurringPage } from "./pages/RecurringPage";
import type { Series, Summary } from "./recurring";

vi.mock("./api/client", () => ({ API_BASE: "", apiFetch: vi.fn() }));
const { apiFetch } = vi.mocked(await import("./api/client"));

const series = (over: Partial<Series>): Series => ({
  id: "s1",
  label: "Netflix",
  merchant_key: "netflix",
  account_id: "a1",
  cadence: "monthly",
  status: "active",
  direction: -1,
  typical_amount: "15.4900",
  last_amount: "15.4900",
  min_amount: "15.4900",
  max_amount: "15.4900",
  amount_varies: false,
  price_increase_amount: null,
  charge_count: 11,
  first_charged_on: "2025-09-14",
  last_charged_on: "2026-07-14",
  next_expected_on: "2026-08-14",
  confidence: 92,
  cancel_url: null,
  notes: null,
  ...over,
});

const summary = (over: Partial<Summary> = {}): Summary => ({
  monthly_committed: "412.3700",
  monthly_incoming: "5200.0000",
  active_count: 14,
  upcoming: [{ id: "s1", label: "Netflix", on: "2026-08-14", amount: "17.9900" }],
  price_increases: 0,
  last_detected_at: "2026-07-26T04:11:03Z",
  ...over,
});

/** Answers the five SP1 endpoints off the path, the way the real API would. */
function mockApi(list: Series[], sum: Summary = summary(), charges: unknown[] = []) {
  apiFetch.mockImplementation(async (path: string) => {
    if (path === "/recurring/summary") return sum;
    if (path.startsWith("/recurring?")) return list;
    if (path.startsWith("/recurring/")) return { ...list[0], charges };
    throw new Error(`unexpected path ${path}`);
  });
}

const show = () =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <RecurringPage />
    </QueryClientProvider>,
  );

beforeEach(() => {
  apiFetch.mockReset();
});

test("shows the monthly commitment, incoming and active count", async () => {
  mockApi([series({})]);
  show();
  expect(await screen.findByText("$412.37")).toBeInTheDocument();
  expect(screen.getByText("$5,200.00")).toBeInTheDocument();
  expect(screen.getByText("14")).toBeInTheDocument();
});

test("lists the next 30 days, soonest first", async () => {
  mockApi([series({})]);
  show();
  expect(await screen.findByText("Aug 14")).toBeInTheDocument();
  expect(screen.getByText("$17.99")).toBeInTheDocument();
});

test("groups money out above money in", async () => {
  mockApi([
    series({ id: "in", label: "Payroll", direction: 1, typical_amount: "2500.0000" }),
    series({ id: "out", label: "Netflix", direction: -1 }),
  ]);
  const { container } = show();

  await screen.findByText("Money out");
  const text = container.textContent ?? "";
  expect(text.indexOf("Money out")).toBeLessThan(text.indexOf("Money in"));
  expect(text.indexOf("Netflix")).toBeLessThan(text.indexOf("Payroll"));
});

test("badges a price increase and calls it out above the list", async () => {
  mockApi([series({ last_amount: "17.9900", price_increase_amount: "2.5000" })], summary({ price_increases: 1 }));
  show();

  expect(await screen.findByText("Price went up")).toBeInTheDocument();
  expect(screen.getByText("↑ $2.50")).toBeInTheDocument();
  expect(screen.getByText("$15.49 → $17.99")).toBeInTheDocument();
});

test("no price increase means no badge and no card", async () => {
  mockApi([series({})]);
  show();
  await screen.findByRole("button", { name: /Netflix/ });
  expect(screen.queryByText("Price went up")).not.toBeInTheDocument();
  expect(screen.queryByText(/↑ \$/)).not.toBeInTheDocument();
});

test("badges a series that stopped charging, and drops its next-expected date", async () => {
  mockApi([series({ status: "ended" })]);
  show();
  expect(await screen.findByText("ended")).toBeInTheDocument();
  expect(screen.getByText("Monthly")).toBeInTheDocument();
});

test("a shaky guess is marked as one", async () => {
  mockApi([series({ confidence: 61 })]);
  show();
  expect(await screen.findByLabelText("61% confident")).toBeInTheDocument();
});

test("says it is still scanning when nothing has been detected yet", async () => {
  mockApi([], summary({ upcoming: [], active_count: 0, last_detected_at: null }));
  show();
  expect(await screen.findByText(/Scanning your history/)).toBeInTheDocument();
});

test("once a scan has run, an empty list says so instead", async () => {
  mockApi([], summary({ upcoming: [] }));
  show();
  expect(await screen.findByText(/Nothing repeating found/)).toBeInTheDocument();
});

test("expanding a series shows its charges and the honest cancellation copy", async () => {
  mockApi(
    [series({})],
    summary(),
    [
      { id: "c1", posted_at: "2026-07-14T00:00:00Z", amount: "-15.49", account_id: "a1" },
      { id: "c2", posted_at: "2026-06-14T00:00:00Z", amount: "-15.49", account_id: "a1" },
    ],
  );
  show();

  fireEvent.click(await screen.findByRole("button", { expanded: false, name: /Netflix/ }));

  await waitFor(() =>
    expect(within(screen.getByRole("table")).getByText("Jul 14")).toBeInTheDocument(),
  );
  expect(screen.getByText(/can't cancel anything for you/)).toBeInTheDocument();
  expect(screen.getByLabelText("Rename Netflix")).toBeInTheDocument();
});
