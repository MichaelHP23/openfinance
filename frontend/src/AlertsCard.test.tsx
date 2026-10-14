import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AlertBell, AlertsCard } from "./AlertsCard";
import { questionFor } from "./alerts";
import type { Alert } from "./alerts";

vi.mock("./api/client", () => ({ apiFetch: vi.fn(), API_BASE: "" }));
import { apiFetch } from "./api/client";

const alert = (over: Partial<Alert> = {}): Alert => ({
  key: "bill_due:s1:2026-10-13",
  kind: "bill_due",
  severity: "info",
  title: "Netflix is due soon",
  body: "About $15.00 expected on 2026-10-13.",
  href: "/recurring",
  occurred_on: "2026-10-13",
  ...over,
});

function show(node: React.ReactNode) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

// Braces matter: mockReset() returns the mock, and vitest treats a function returned
// from beforeEach as a teardown callback — it would call apiFetch after every test.
beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

describe("AlertsCard", () => {
  it("lists alerts with a link to where each one is handled", async () => {
    vi.mocked(apiFetch).mockResolvedValue([alert()]);
    show(<AlertsCard />);
    const link = await screen.findByRole("link", { name: "Netflix is due soon" });
    expect(link).toHaveAttribute("href", "/recurring");
    expect(screen.getByText("About $15.00 expected on 2026-10-13.")).toBeInTheDocument();
  });

  it("renders nothing when there are no alerts", async () => {
    vi.mocked(apiFetch).mockResolvedValue([]);
    const { container } = show(<AlertsCard />);
    await waitFor(() => expect(apiFetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("shows five and says how many more there are", async () => {
    const many = Array.from({ length: 7 }, (_, i) =>
      alert({ key: `k${i}`, title: `Alert ${i}` }),
    );
    vi.mocked(apiFetch).mockResolvedValue(many);
    show(<AlertsCard />);
    expect(await screen.findByText("Alert 4")).toBeInTheDocument();
    expect(screen.queryByText("Alert 5")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show 2 more" }));
    expect(await screen.findByText("Alert 6")).toBeInTheDocument();
  });

  it("says alerts could not be loaded instead of looking all-clear", async () => {
    vi.mocked(apiFetch).mockImplementation(async () => {
      throw new Error("boom");
    });
    show(<AlertsCard />);
    expect(await screen.findByText("Couldn't load alerts.")).toBeInTheDocument();
  });

  it("posts the key when an alert is dismissed", async () => {
    vi.mocked(apiFetch).mockResolvedValue([alert()]);
    show(<AlertsCard />);
    fireEvent.click(await screen.findByRole("button", { name: "Dismiss Netflix is due soon" }));
    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith("/alerts/dismiss", {
        method: "POST",
        body: JSON.stringify({ key: "bill_due:s1:2026-10-13" }),
      }),
    );
  });
});

describe("Ask advisor", () => {
  const withAdvisor = (available: boolean, alerts: Alert[]) =>
    vi.mocked(apiFetch).mockImplementation(async (path: string) =>
      path === "/insights/available" ? { available } : alerts,
    );

  it("hands the assistant a question built from the alert", async () => {
    withAdvisor(true, [
      alert({
        kind: "price_increase",
        title: "Netflix went up",
        body: "The last charge was $3.00 higher than usual.",
      }),
    ]);
    const onAsk = vi.fn();
    show(<AlertsCard onAsk={onAsk} />);
    fireEvent.click(await screen.findByRole("button", { name: "Ask advisor about Netflix went up" }));
    expect(onAsk).toHaveBeenCalledWith(
      "Netflix went up. The last charge was $3.00 higher than usual. What are my options?",
    );
  });

  it("is not offered when no model is configured", async () => {
    withAdvisor(false, [alert()]);
    show(<AlertsCard onAsk={vi.fn()} />);
    await screen.findByText("Netflix is due soon");
    expect(screen.queryByRole("button", { name: /Ask advisor/ })).not.toBeInTheDocument();
  });

  it("asks a different question for each kind, and a plain one for a kind it does not know", () => {
    const kinds = [
      "bill_due",
      "price_increase",
      "yearly_renewal",
      "still_billing",
      "low_balance",
      "over_budget",
      "large_charge",
    ];
    const questions = kinds.map((kind) => questionFor(alert({ kind })));
    expect(new Set(questions).size).toBe(kinds.length);
    expect(questionFor(alert({ kind: "from_the_future", title: "T", body: "B." }))).toBe(
      "T. B. What should I do about this?",
    );
  });
});

describe("AlertBell", () => {
  it("names the count for screen readers", async () => {
    vi.mocked(apiFetch).mockResolvedValue([alert(), alert({ key: "k2" })]);
    show(<AlertBell />);
    expect(await screen.findByRole("link", { name: "2 alerts" })).toBeInTheDocument();
  });

  it("does not claim there are no alerts when the fetch failed", async () => {
    vi.mocked(apiFetch).mockImplementation(async () => {
      throw new Error("boom");
    });
    show(<AlertBell />);
    expect(await screen.findByRole("link", { name: "Alerts unavailable" })).toBeInTheDocument();
  });

  it("says so when there are none", async () => {
    vi.mocked(apiFetch).mockResolvedValue([]);
    show(<AlertBell />);
    expect(await screen.findByRole("link", { name: "No alerts" })).toBeInTheDocument();
  });
});
