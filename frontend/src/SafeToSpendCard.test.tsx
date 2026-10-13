import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SafeToSpendCard } from "./SafeToSpendCard";

vi.mock("./api/client", () => ({ apiFetch: vi.fn(), API_BASE: "" }));
import { apiFetch } from "./api/client";

function show() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <SafeToSpendCard />
    </QueryClientProvider>,
  );
}

// Braces matter: a function returned from beforeEach is run by vitest as teardown.
beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

describe("SafeToSpendCard", () => {
  it("shows the amount, the payday it holds until, and the bills before it", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      amount: "300.0000",
      until: "2026-10-22",
      bills_due: 2,
    });
    show();
    expect(await screen.findByText("$300.00")).toBeInTheDocument();
    expect(screen.getByText(/until payday on Oct 22/)).toBeInTheDocument();
    expect(screen.getByText(/2 bills due before then/)).toBeInTheDocument();
  });

  it("names a thirty-day window when no payday is known", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ amount: "1100.0000", until: null, bills_due: 1 });
    show();
    expect(await screen.findByText(/over the next 30 days/)).toBeInTheDocument();
    expect(screen.getByText(/1 bill due before then/)).toBeInTheDocument();
  });

  it("says plainly when nothing is spare", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ amount: "0", until: "2026-10-22", bills_due: 3 });
    show();
    expect(await screen.findByText("$0.00")).toBeInTheDocument();
    expect(screen.getByText(/Nothing spare/)).toBeInTheDocument();
  });

  it("renders nothing rather than a wrong number when the fetch fails", async () => {
    vi.mocked(apiFetch).mockImplementation(async () => {
      throw new Error("boom");
    });
    const { container } = show();
    await vi.waitFor(() => expect(apiFetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
