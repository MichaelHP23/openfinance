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
  ignored: false,
  tags: [],
};

beforeEach(() => vi.mocked(apiFetch).mockReset());

// Old fixture-style mock, still used by the two list-rendering tests below. Equality,
// not .startsWith: apiFetch here is a shared vi.fn() reset between tests, and matching
// on exact path (with a fallback) is what the rest of this file's mocks do too.
function listFixtureImpl(path: string) {
  if (path === "/categories" || path === "/transactions/tags") return Promise.resolve([]);
  return Promise.resolve([
    {
      id: "1",
      posted_at: "2026-01-01T12:00:00Z",
      merchant_raw: "Starbucks",
      amount: "-9.99",
      currency: "USD",
      category_id: null,
      ignored: false,
      tags: [],
    },
    {
      id: "2",
      posted_at: "2026-01-02T12:00:00Z",
      merchant_raw: "Payroll",
      amount: "2500.00",
      currency: "USD",
      category_id: null,
      ignored: false,
      tags: [],
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
  expect((await screen.findAllByText("Starbucks")).length).toBeGreaterThan(0);
  expect(screen.getAllByText("Jan 1")[0]).toBeInTheDocument();
});

test("signs amounts: outflow bare, inflow with a plus", async () => {
  vi.mocked(apiFetch).mockImplementation(listFixtureImpl as never);
  renderList();
  expect((await screen.findAllByText("-$9.99")).length).toBeGreaterThan(0);
  expect(screen.getAllByText("+$2,500.00")[0]).toBeInTheDocument();
});

test("keeps the chosen category visible while its PATCH is in flight", async () => {
  vi.mocked(apiFetch).mockImplementation(async (path: string) => {
    if (path === "/categories") return categories;
    if (path === "/transactions/1") return new Promise(() => {}); // never resolves
    return [];
  });
  render(<TxnRows txns={[txn]} />, { wrapper });
  const selects = (await screen.findAllByLabelText(
    "Category for Whole Foods",
  )) as HTMLSelectElement[];
  await screen.findAllByRole("option", { name: "B" });
  for (const select of selects) fireEvent.change(select, { target: { value: "c2" } });
  await waitFor(() => selects.forEach((s) => expect(s.value).toBe("c2")));
});

test("keeps the chosen category visible after the PATCH succeeds but before the refetch lands", async () => {
  vi.mocked(apiFetch).mockImplementation(async (path: string) => {
    if (path === "/categories") return categories;
    if (path === "/transactions/1") return {}; // PATCH resolves immediately
    if (path === "/transactions") return new Promise(() => {}); // refetch never lands
    return [];
  });
  render(<TxnRows txns={[txn]} />, { wrapper });
  const selects = (await screen.findAllByLabelText(
    "Category for Whole Foods",
  )) as HTMLSelectElement[];
  await screen.findAllByRole("option", { name: "B" });
  for (const select of selects) fireEvent.change(select, { target: { value: "c2" } });
  // The rule prompt only renders from the mutation's onSuccess, so waiting for it
  // proves onSuccess has already run — this is the moment a naive implementation
  // that clears its optimistic state in onSuccess would snap back to the stale
  // txn.category_id prop, since the invalidated ["transactions"] refetch (which
  // would supply a fresh prop) never resolves in this test.
  await screen.findAllByText("Make it a rule");
  selects.forEach((s) => expect(s.value).toBe("c2"));
});

test("shows the PATCH error message when setting a category fails", async () => {
  vi.mocked(apiFetch).mockImplementation(async (path: string) => {
    if (path === "/categories") return categories;
    if (path === "/transactions/1") throw new Error("Category not found");
    return [];
  });
  render(<TxnRows txns={[txn]} />, { wrapper });
  const selects = await screen.findAllByLabelText("Category for Whole Foods");
  await screen.findAllByRole("option", { name: "B" });
  for (const select of selects) fireEvent.change(select, { target: { value: "c2" } });
  expect((await screen.findAllByText("Category not found")).length).toBeGreaterThan(0);
});

test("keeps the rule prompt open and shows the error when 'Make it a rule' fails", async () => {
  vi.mocked(apiFetch).mockImplementation(async (path: string) => {
    if (path === "/categories") return categories;
    if (path === "/transactions/1") return {};
    if (path === "/category-rules") throw new Error("Category not found");
    return [];
  });
  render(<TxnRows txns={[txn]} />, { wrapper });
  const selects = await screen.findAllByLabelText("Category for Whole Foods");
  await screen.findAllByRole("option", { name: "B" });
  for (const select of selects) fireEvent.change(select, { target: { value: "c2" } });
  const makeRuleBtns = await screen.findAllByText("Make it a rule");
  makeRuleBtns.forEach((btn) => fireEvent.click(btn));
  expect((await screen.findAllByText("Category not found")).length).toBeGreaterThan(0);
  expect(screen.getAllByText("Make it a rule")[0]).toBeInTheDocument();
});

const patchBody = () => {
  const call = vi.mocked(apiFetch).mock.calls.find(([path]) => path === "/transactions/1");
  return JSON.parse(((call ?? [])[1] as RequestInit).body as string);
};

test("Ignore sends ignored: true", async () => {
  vi.mocked(apiFetch).mockResolvedValue([] as never);
  render(<TxnRows txns={[txn]} />, { wrapper });
  fireEvent.click(screen.getAllByRole("button", { name: "Ignore Whole Foods" })[0]);
  await waitFor(() => expect(patchBody()).toEqual({ ignored: true }));
});

test("an ignored row says so and offers to count it again", async () => {
  vi.mocked(apiFetch).mockResolvedValue([] as never);
  render(<TxnRows txns={[{ ...txn, ignored: true }]} />, { wrapper });
  expect(screen.getByText("Ignored")).toBeInTheDocument();
  fireEvent.click(screen.getAllByRole("button", { name: "Count Whole Foods" })[0]);
  await waitFor(() => expect(patchBody()).toEqual({ ignored: false }));
});

test("editing tags sends them as a list when the field loses focus", async () => {
  vi.mocked(apiFetch).mockResolvedValue([] as never);
  render(<TxnRows txns={[{ ...txn, tags: ["tax"] }]} />, { wrapper });
  const input = screen.getAllByLabelText("Tags for Whole Foods")[0] as HTMLInputElement;
  expect(input.value).toBe("tax");
  fireEvent.change(input, { target: { value: "tax, Reimbursable ,," } });
  fireEvent.blur(input);
  await waitFor(() => expect(patchBody()).toEqual({ tags: ["tax", "Reimbursable"] }));
});

test("leaving the tags field unchanged sends nothing", async () => {
  vi.mocked(apiFetch).mockResolvedValue([] as never);
  render(<TxnRows txns={[{ ...txn, tags: ["tax"] }]} />, { wrapper });
  fireEvent.blur(screen.getAllByLabelText("Tags for Whole Foods")[0]);
  await screen.findAllByLabelText("Category for Whole Foods");
  expect(vi.mocked(apiFetch).mock.calls.some(([path]) => path === "/transactions/1")).toBe(false);
});

test("a rejected tag shows the API's reason", async () => {
  vi.mocked(apiFetch).mockImplementation(async (path: string) => {
    if (path === "/transactions/1") throw new Error("at most 10 tags per transaction");
    return [];
  });
  render(<TxnRows txns={[txn]} />, { wrapper });
  const input = screen.getAllByLabelText("Tags for Whole Foods")[0];
  fireEvent.change(input, { target: { value: "a" } });
  fireEvent.blur(input);
  expect(await screen.findByText("at most 10 tags per transaction")).toBeInTheDocument();
});

test("picking a tag filters the list by it", async () => {
  vi.mocked(apiFetch).mockImplementation(async (path: string) => {
    if (path === "/transactions/tags") return ["tax"];
    if (path === "/transactions?tag=tax") return [{ ...txn, merchant_raw: "Accountant", tags: ["tax"] }];
    if (path === "/transactions") return [txn];
    return [];
  });
  renderList();
  await screen.findAllByText("Whole Foods");
  await screen.findByRole("option", { name: "tax" });
  fireEvent.change(screen.getByLabelText("Filter by tag"), { target: { value: "tax" } });
  expect((await screen.findAllByText("Accountant")).length).toBeGreaterThan(0);
});
