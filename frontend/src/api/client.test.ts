import { describe, it, expect, vi } from "vitest";
import { apiFetch } from "./client";

describe("apiFetch", () => {
  it("throws the API detail message on error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: "nope" }), { status: 401 })),
    );
    await expect(apiFetch("/x")).rejects.toThrow("nope");
  });

  it("returns parsed json on success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ a: 1 }), { status: 200 })),
    );
    expect(await apiFetch("/x")).toEqual({ a: 1 });
  });

  it("sends cookies", async () => {
    const spy = vi.fn(async (_url: string, _init?: RequestInit) => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", spy);
    await apiFetch("/x");
    expect(spy.mock.calls[0][1]).toMatchObject({ credentials: "include" });
  });

  it("attaches X-CSRF-Token on a mutating request when the cookie is present", async () => {
    document.cookie = "csrf_token=abc123";
    const spy = vi.fn(async (_url: string, _init?: RequestInit) => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", spy);
    await apiFetch("/x", { method: "POST", body: "{}" });
    const [, init] = spy.mock.calls[0];
    expect((init?.headers as Record<string, string>)["X-CSRF-Token"]).toBe("abc123");
    document.cookie = "csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });

  it("does not attach X-CSRF-Token on a GET request", async () => {
    document.cookie = "csrf_token=abc123";
    const spy = vi.fn(async (_url: string, _init?: RequestInit) => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", spy);
    await apiFetch("/x");
    const [, init] = spy.mock.calls[0];
    expect((init?.headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
    document.cookie = "csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });
});
