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
