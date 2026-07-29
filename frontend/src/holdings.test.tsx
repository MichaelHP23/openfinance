import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { expect, test, vi } from "vitest";
import { HoldingsList } from "./holdings";

const holdings = [
  {
    security_id: "s1",
    symbol: "VTI",
    name: "Vanguard Total Stock Market ETF",
    currency: "USD",
    category: "Domestic equity",
    units: "112.5",
    avg_cost: "198.4412",
    cost_base: "22324.63",
    price: "241.30",
    priced_on: "2026-07-24",
    market_value: "27146.25",
    unrealized: "4821.62",
    unrealized_pct: "21.60",
    dividends: "412.88",
    share_pct: "100",
    by_account: [{ account_id: "a1", name: "Roth IRA", units: "40" }],
  },
];

const apiFetch = vi.fn(async (path: string) => {
  if (path.startsWith("/investments/holdings")) {
    return { holdings, priced_through: "2026-07-24" };
  }
  if (path.startsWith("/investments/prices")) {
    return {};
  }
  throw new Error(`unexpected path in test: ${path}`);
});

vi.mock("./api/client", () => ({
  API_BASE: "",
  apiFetch: (...args: [string, RequestInit?]) => apiFetch(...args),
}));

const renderList = () =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <HoldingsList />
    </QueryClientProvider>,
  );

test("renders a holding with its price, market value and toned unrealized gain", async () => {
  renderList();
  expect((await screen.findAllByText("VTI")).length).toBeGreaterThan(0);
  expect(screen.getByText("$241.30")).toBeInTheDocument();
  expect(screen.getAllByText("$27,146.25")[0]).toBeInTheDocument();
  expect(screen.getByText("+21.6%")).toBeInTheDocument();
});

test("expanding a holding reveals its per-account breakdown", async () => {
  renderList();
  const symbols = await screen.findAllByText("VTI");
  const inTable = symbols.find((el) => el.closest("table"));
  expect(inTable).toBeTruthy();
  fireEvent.click(inTable!);
  expect(await screen.findByText("Roth IRA")).toBeInTheDocument();
});

test("an unpriced holding shows 'no price' instead of a guessed value, and offers a set-price form", async () => {
  apiFetch.mockImplementationOnce(async () => ({
    holdings: [{ ...holdings[0], security_id: "s2", symbol: "PRIVCO", price: null, market_value: null }],
    priced_through: null,
  }));
  renderList();
  expect((await screen.findAllByText("no price")).length).toBeGreaterThan(0);
  expect(screen.getAllByLabelText("Set price").length).toBeGreaterThan(0);
});

test("saving a manual price posts to /investments/prices", async () => {
  // A successful save invalidates the holdings query, so the list refetches — the
  // fixture has to survive both the initial load and that refetch, not just one call.
  const unpriced = {
    holdings: [{ ...holdings[0], security_id: "s2", symbol: "PRIVCO", price: null, market_value: null }],
    priced_through: null,
  };
  apiFetch.mockImplementation(async (path: string) => {
    if (path.startsWith("/investments/holdings")) return unpriced;
    if (path.startsWith("/investments/prices")) return {};
    throw new Error(`unexpected path in test: ${path}`);
  });
  renderList();
  const [input] = await screen.findAllByLabelText("Set price");
  fireEvent.change(input, { target: { value: "42.50" } });
  const form = input.closest("form")!;
  fireEvent.submit(form);

  // Two matches expected: the desktop table row and the mobile card both render in jsdom.
  expect((await screen.findAllByText("PRIVCO")).length).toBeGreaterThan(0);
  const call = apiFetch.mock.calls.find(([path]) => path === "/investments/prices");
  expect(call).toBeTruthy();
  const body = JSON.parse((call![1] as RequestInit).body as string);
  expect(body).toMatchObject({ security_id: "s2", close: "42.50" });
});
