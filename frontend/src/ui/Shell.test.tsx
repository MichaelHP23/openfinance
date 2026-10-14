import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test, vi } from "vitest";
import { Shell } from "./Shell";

vi.mock("../api/client", () => ({ apiFetch: vi.fn().mockResolvedValue([]), API_BASE: "" }));

// The glyph in front of each label is decorative (aria-hidden); compare the words.
const label = (a: HTMLElement) => (a.textContent ?? "").replace(/^[^A-Za-z]+/, "");

const show = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <Shell localMode>content</Shell>
      </MemoryRouter>
    </QueryClientProvider>,
  );

test("the sidebar lists the money pages in order, with Settings behind a gear instead", () => {
  show();
  const sidebar = screen.getByRole("navigation", { name: "Main" });
  expect(within(sidebar).getAllByRole("link").map(label)).toEqual([
    "Dashboard",
    "Recurring",
    "Spending",
    "Transactions",
    "Budgets",
    "Net Worth",
    "Goals",
    "Accounts",
    "Investments",
  ]);
  expect(screen.getAllByRole("link", { name: "Settings" })[0]).toHaveAttribute("href", "/settings");
});

test("the phone tab bar has four destinations and More", () => {
  show();
  const tabs = screen.getByRole("navigation", { name: "Tabs" });
  expect(within(tabs).getAllByRole("link").map(label)).toEqual([
    "Dashboard",
    "Recurring",
    "Spending",
    "Transactions",
  ]);
  expect(within(tabs).getByRole("button", { name: "More" })).toBeInTheDocument();
});
