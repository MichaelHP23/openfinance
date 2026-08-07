import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { NetWorthChart } from "./insights";
import type { NetWorthPoint } from "./data";

const point = (on: string, net: number): NetWorthPoint => ({
  on,
  assets: net,
  debts: 0,
  net,
});

test("says nothing is recorded when there is no history", () => {
  render(<NetWorthChart points={[]} />);
  expect(screen.getByText(/No history yet/)).toBeInTheDocument();
});

test("a single day cannot make a line, and says so", () => {
  render(<NetWorthChart points={[point("2026-07-01", 100)]} />);
  expect(screen.getByText(/One day recorded/)).toBeInTheDocument();
});

test("draws a path and reports the change across the window", () => {
  const { container } = render(
    <NetWorthChart
      points={[
        point("2026-07-01", 1000),
        point("2026-07-02", 1500),
        point("2026-07-03", 2000),
      ]}
    />,
  );

  const paths = container.querySelectorAll("path");
  expect(paths.length).toBe(2); // area fill + line
  expect(paths[1].getAttribute("d")).toMatch(/^M0\.0,/);
  expect(screen.getByText(/\+\$1,000\.00 over 3 days/)).toBeInTheDocument();
});

test("a falling net worth reads as a loss", () => {
  render(<NetWorthChart points={[point("2026-07-01", 2000), point("2026-07-02", 1200)]} />);
  expect(screen.getByText(/-\$800\.00 over 2 days/)).toBeInTheDocument();
});

test("a flat line does not divide by zero", () => {
  const { container } = render(
    <NetWorthChart points={[point("2026-07-01", 500), point("2026-07-02", 500)]} />,
  );
  expect(container.querySelector("path")?.getAttribute("d")).not.toMatch(/NaN/);
});

import { fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { describe, beforeEach, it, vi } from "vitest";
import { Assistant } from "./insights";

vi.mock("./api/client", () => ({ apiFetch: vi.fn(), API_BASE: "" }));
import { apiFetch } from "./api/client";

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

describe("Assistant", () => {
  it("does not render when the assistant is unavailable", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ available: false });
    render(<Assistant />, { wrapper });
    await waitFor(() =>
      expect(screen.queryByText(/What's up with my money/)).not.toBeInTheDocument(),
    );
  });

  it("renders an answer with a collapsible trace, and keeps prior turns after a second question", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/insights/available") return { available: true };
      if (path === "/insights/ask")
        return {
          answer: "## Where you stand\n- Net worth is up.",
          trace: [
            { tool: "net_worth_history", args: { months: 3 }, result_summary: '{"points": []}' },
          ],
          model: "claude-sonnet-5",
        };
      throw new Error(`unexpected path ${path}`);
    });

    render(<Assistant />, { wrapper });
    const input = await screen.findByLabelText("Question");

    fireEvent.change(input, { target: { value: "How's my net worth?" } });
    fireEvent.click(screen.getByText("Ask"));
    await screen.findByText(/Net worth is up/);

    expect(screen.getByText(/1 tool call/)).toBeInTheDocument();
    fireEvent.click(screen.getByText(/1 tool call/));
    expect(screen.getByText(/net_worth_history/)).toBeInTheDocument();

    // A second question doesn't erase the first turn.
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "What about spending?" } });
    fireEvent.click(screen.getByText("Ask"));
    await waitFor(() => expect(vi.mocked(apiFetch)).toHaveBeenCalledTimes(3));
    // The mock answers every question identically, so the first turn's answer text
    // now appears twice — once per turn — rather than being replaced.
    expect(screen.getAllByText(/Net worth is up/)).toHaveLength(2);
  });
});
