/**
 * Same host the page was served from, port 8000 — so the app works unchanged on
 * localhost, over a LAN address, or across a Tailscale tailnet from a phone.
 * A baked-in "localhost" would make the phone call itself.
 */
const inferred =
  typeof window === "undefined"
    ? "http://localhost:8000"
    : `${window.location.protocol}//${window.location.hostname}:8000`;

export const API_BASE = import.meta.env.VITE_API_URL || inferred;

function readCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

export async function apiFetch<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const method = (opts.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(opts.headers as Record<string, string> | undefined),
  };
  if (method !== "GET" && method !== "HEAD") {
    const token = readCookie("csrf_token");
    if (token) headers["X-CSRF-Token"] = token;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...opts,
    credentials: "include",
    headers,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    // FastAPI errors carry `detail`; slowapi's rate limiter carries `error`.
    const message =
      res.status === 429
        ? "Too many attempts — wait a minute and try again."
        : (body.detail ?? body.error ?? res.statusText);
    throw new Error(message);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}
