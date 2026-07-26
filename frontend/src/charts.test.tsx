import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { AllocationBar, AreaChart, BarChart } from "./charts";
import { SERIES } from "./palette";

const points = [
  { label: "2026-07-01", value: 1000 },
  { label: "2026-07-02", value: 1400 },
  { label: "2026-07-03", value: 1200 },
];

describe("AreaChart", () => {
  test("draws a fill and a line once measured", () => {
    const { container } = render(<AreaChart points={points} />);
    expect(container.querySelectorAll("path")).toHaveLength(2);
    expect(container.querySelector("svg")).toHaveAttribute("role", "img");
  });

  test("labels the range for screen readers", () => {
    render(<AreaChart points={points} valueLabel="Net worth" />);
    expect(screen.getByRole("img").getAttribute("aria-label")).toBe(
      "Net worth from $1,000.00 to $1,200.00",
    );
  });

  test("a flat series does not produce NaN geometry", () => {
    const flat = [
      { label: "a", value: 500 },
      { label: "b", value: 500 },
    ];
    const { container } = render(<AreaChart points={flat} />);
    expect(container.querySelector("path")?.getAttribute("d")).not.toMatch(/NaN/);
  });

  test("hovering reveals the value under the pointer", () => {
    const { container } = render(<AreaChart points={points} />);
    const svg = container.querySelector("svg")!;
    svg.getBoundingClientRect = () => ({ left: 0, width: 600 }) as DOMRect;

    fireEvent.pointerMove(svg, { clientX: 300 });
    expect(screen.getByText("$1,400.00")).toBeInTheDocument();
    expect(screen.getByText("2026-07-02")).toBeInTheDocument();

    fireEvent.pointerLeave(svg);
    expect(screen.queryByText("$1,400.00")).not.toBeInTheDocument();
  });
});

describe("BarChart", () => {
  const bars = [
    { label: "May", value: 10 },
    { label: "Jun", value: 40 },
    { label: "Jul", value: 20 },
  ];

  test("labels each bar with its value for assistive tech", () => {
    render(<BarChart bars={bars} />);
    expect(screen.getByLabelText("Jun: $40.00")).toBeInTheDocument();
  });

  test("calls out the peak instead of labelling every bar", () => {
    render(<BarChart bars={bars} />);
    expect(screen.getByText(/peak \$40 in Jun/)).toBeInTheDocument();
  });

  test("hover replaces the peak note with the hovered bar", () => {
    render(<BarChart bars={bars} />);
    fireEvent.pointerEnter(screen.getByLabelText("Jul: $20.00"));
    expect(screen.getByText("Jul · $20.00")).toBeInTheDocument();
  });
});

describe("AllocationBar", () => {
  const slices = [
    { label: "Brokerage", value: 700, share: 70 },
    { label: "IRA", value: 300, share: 30 },
  ];

  test("names every slice, so identity never depends on colour alone", () => {
    render(<AllocationBar slices={slices} />);
    expect(screen.getByText("Brokerage")).toBeInTheDocument();
    expect(screen.getByText("70%")).toBeInTheDocument();
    expect(screen.getByText("$300.00")).toBeInTheDocument();
  });

  test("assigns series colours in fixed order", () => {
    const { container } = render(<AllocationBar slices={slices} />);
    const swatches = container.querySelectorAll("li span:first-child");
    expect((swatches[0] as HTMLElement).style.background).toBe("rgb(57, 135, 229)");
    expect(SERIES[0]).toBe("#3987e5");
  });

  test("a sixth category folds into Other rather than reusing a hue", () => {
    const many = Array.from({ length: 7 }, (_, i) => ({
      label: `Account ${i}`,
      value: 100,
      share: 100 / 7,
    }));
    render(<AllocationBar slices={many} />);
    expect(screen.getByText("Other")).toBeInTheDocument();
    expect(screen.queryByText("Account 6")).not.toBeInTheDocument();
  });
});
