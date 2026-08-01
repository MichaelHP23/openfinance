import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, expect, test, vi } from "vitest";
import { TransactionList, TxnRows } from "./transactions";
import type { Txn } from "./data";

vi.mock("./api/client", () => ({ API_BASE: "", apiFetch: vi.fn() }));
import { apiFetch } from "./api/client";

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const categories = [
  { id: "g1", name: "Group", parent_id: null, is_system: true },
  { id: "c1", name: "A", parent_id: "g1", is_system: true },
  { id: "c2", name: "B", parent_id: "g1", is_system: true },
];

const txn: Txn = {
  id: "1",
  posted_at: "2026-01-01T12:00:00Z",
  merchant_raw: "Whole Foods",
  amount: "-9.99",
  currency: "USD",
  category_id: "c1",
};

beforeEach(() => vi.mocked(apiFetch).mockReset());

// Old fixture-style mock, still used by the two list-rendering tests below. Equality,
// not .startsWith: apiFetch here is a shared vi.fn() reset between tests, and matching
// on exact path (with a fallback) is what the rest of this file's mocks do too.
function listFixtureImpl(path: string) {
  if (path === "/categories") return Promise.resolve([]);
  return Promise.resolve([
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
  ]);
}

// retry: false — a mocked apiFetch that briefly errors (e.g. an unhandled path in a
// switch above) would otherwise leave a retry timer alive past the end of the test,
// which then fires against whatever the next test's mock looks like.
const renderList = () => render(<TransactionList />, { wrapper });

test("renders transactions with a short date", async () => {
  vi.mocked(apiFetch).mockImplementation(listFixtureImpl as never);
  renderList();
  expect(await screen.findByText("Starbucks")).toBeInTheDocument();
  expect(screen.getByText("Jan 1")).toBeInTheDocument();
});

test("signs amounts: outflow bare, inflow with a plus", async () => {
  vi.mocked(apiFetch).mockImplementation(listFixtureImpl as never);
  renderList();
  expect(await screen.findByText("-$9.99")).toBeInTheDocument();
  expect(screen.getByText("+$2,500.00")).toBeInTheDocument();
});

test("keeps the chosen category visible while its PATCH is in flight", async () => {
  vi.mocked(apiFetch).mockImplementation(async (path: string) => {
    if (path === "/categories") return categories;
    if (path === "/transactions/1") return new Promise(() => {}); // never resolves
    return [];
  });
  render(<TxnRows txns={[txn]} />, { wrapper });
  const select = (await screen.findByLabelText(
    "Category for Whole Foods",
  )) as HTMLSelectElement;
  await screen.findByRole("option", { name: "B" });
  fireEvent.change(select, { target: { value: "c2" } });
  await waitFor(() => expect(select.value).toBe("c2"));
});

test("keeps the chosen category visible after the PATCH succeeds but before the refetch lands", async () => {
  vi.mocked(apiFetch).mockImplementation(async (path: string) => {
    if (path === "/categories") return categories;
    if (path === "/transactions/1") return {}; // PATCH resolves immediately
    if (path === "/transactions") return new Promise(() => {}); // refetch never lands
    return [];
  });
  render(<TxnRows txns={[txn]} />, { wrapper });
  const select = (await screen.findByLabelText(
    "Category for Whole Foods",
  )) as HTMLSelectElement;
  await screen.findByRole("option", { name: "B" });
  fireEvent.change(select, { target: { value: "c2" } });
  // The rule prompt only renders from the mutation's onSuccess, so waiting for it
  // proves onSuccess has already run — this is the moment a naive implementation
  // that clears its optimistic state in onSuccess would snap back to the stale
  // txn.category_id prop, since the invalidated ["transactions"] refetch (which
  // would supply a fresh prop) never resolves in this test.
  await screen.findByText("Make it a rule");
  expect(select.value).toBe("c2");
});

test("shows the PATCH error message when setting a category fails", async () => {
  vi.mocked(apiFetch).mockImplementation(async (path: string) => {
    if (path === "/categories") return categories;
    if (path === "/transactions/1") throw new Error("Category not found");
    return [];
  });
  render(<TxnRows txns={[txn]} />, { wrapper });
  const select = await screen.findByLabelText("Category for Whole Foods");
  await screen.findByRole("option", { name: "B" });
  fireEvent.change(select, { target: { value: "c2" } });
  expect(await screen.findByText("Category not found")).toBeInTheDocument();
});

test("keeps the rule prompt open and shows the error when 'Make it a rule' fails", async () => {
  vi.mocked(apiFetch).mockImplementation(async (path: string) => {
    if (path === "/categories") return categories;
    if (path === "/transactions/1") return {};
    if (path === "/category-rules") throw new Error("Category not found");
    return [];
  });
  render(<TxnRows txns={[txn]} />, { wrapper });
  const select = await screen.findByLabelText("Category for Whole Foods");
  await screen.findByRole("option", { name: "B" });
  fireEvent.change(select, { target: { value: "c2" } });
  const makeRuleBtn = await screen.findByText("Make it a rule");
  fireEvent.click(makeRuleBtn);
  expect(await screen.findByText("Category not found")).toBeInTheDocument();
  expect(screen.getByText("Make it a rule")).toBeInTheDocument();
});
