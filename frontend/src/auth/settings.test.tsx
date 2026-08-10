import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { useSessions, useChangePassword } from "./settings";

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("useSessions", () => {
  it("fetches the session list", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify([{ id: "1", is_current: true }]), { status: 200 })),
    );
    const { result } = renderHook(() => useSessions(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
  });
});

describe("useChangePassword", () => {
  it("posts current and new password", async () => {
    const spy = vi.fn(async (_url: string, _init?: RequestInit) => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", spy);
    const { result } = renderHook(() => useChangePassword(), { wrapper });
    await result.current.mutateAsync({ current_password: "a", new_password: "b" });
    const [url, init] = spy.mock.calls[0];
    expect(String(url)).toContain("/auth/password");
    expect(init?.method).toBe("POST");
  });
});
