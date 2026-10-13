import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AlertBell, AlertsCard } from "./AlertsCard";
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
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => vi.mocked(apiFetch).mockReset());

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
    expect(screen.getByText("2 more")).toBeInTheDocument();
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

describe("AlertBell", () => {
  it("names the count for screen readers", async () => {
    vi.mocked(apiFetch).mockResolvedValue([alert(), alert({ key: "k2" })]);
    show(<AlertBell />);
    expect(await screen.findByRole("link", { name: "2 alerts" })).toBeInTheDocument();
  });

  it("says so when there are none", async () => {
    vi.mocked(apiFetch).mockResolvedValue([]);
    show(<AlertBell />);
    expect(await screen.findByRole("link", { name: "No alerts" })).toBeInTheDocument();
  });
});
