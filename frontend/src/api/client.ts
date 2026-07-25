export const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export async function apiFetch<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...opts,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...opts.headers },
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
