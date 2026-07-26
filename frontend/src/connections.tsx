import { useState } from "react";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./api/client";

export type Connection = {
  id: string;
  provider: string;
  status: string;
  last_synced_at: string | null;
  is_demo: boolean;
};

type SyncResult = {
  is_demo: boolean;
  accounts_added: number;
  accounts_updated: number;
  transactions_added: number;
  transactions_skipped: number;
  errors: string[];
};

const summarize = (r: SyncResult) =>
  [
    r.accounts_added ? `${r.accounts_added} new account${r.accounts_added > 1 ? "s" : ""}` : "",
    r.transactions_added ? `${r.transactions_added} new transaction${r.transactions_added > 1 ? "s" : ""}` : "",
    r.transactions_skipped ? `${r.transactions_skipped} already had` : "",
  ]
    .filter(Boolean)
    .join(" · ") || "Nothing new";

const syncedAt = (iso: string | null) =>
  iso
    ? `Synced ${new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}`
    : "Never synced";

function useRefreshAll() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["accounts"] });
    qc.invalidateQueries({ queryKey: ["transactions"] });
    qc.invalidateQueries({ queryKey: ["connections"] });
  };
}

export function ConnectBank() {
  const refresh = useRefreshAll();
  const [result, setResult] = useState("");
  const { register, handleSubmit, reset } = useForm<{ setup_token: string }>();

  const link = useMutation({
    mutationFn: (body: { setup_token: string }) =>
      apiFetch<SyncResult>("/connections/simplefin", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: (r) => {
      setResult(
        r.is_demo
          ? `Connected SimpleFIN's DEMO bank — this is invented data, not your accounts. ${summarize(r)}`
          : summarize(r),
      );
      reset();
      refresh();
    },
  });

  return (
    <div className="card p-5">
      <h2 className="mb-1 text-sm font-medium">Connect a bank</h2>
      <p className="mb-4 max-w-xl text-[13px] leading-relaxed text-muted">
        Uses{" "}
        <a
          href="https://beta-bridge.simplefin.org/"
          target="_blank"
          rel="noreferrer"
          className="text-acid underline-offset-2 hover:underline"
        >
          SimpleFIN Bridge
        </a>
        . Link your bank there, then paste the setup token it gives you. Read-only, and the
        token is single-use — it's exchanged for a stored access key and can't be reused.
      </p>

      <form
        onSubmit={handleSubmit((f) => link.mutate(f))}
        className="flex flex-wrap items-end gap-3"
      >
        <label className="flex min-w-0 flex-1 flex-col gap-1.5">
          <span className="label">Setup token</span>
          <input
            className="w-full font-mono text-xs"
            placeholder="aHR0cHM6Ly9icmlkZ2Uuc2ltcGxlZmluLm9yZy8…"
            aria-label="Setup token"
            {...register("setup_token", { required: true })}
          />
        </label>
        <button disabled={link.isPending} className="btn">
          {link.isPending ? "Connecting…" : "Connect"}
        </button>
      </form>

      {link.isError && (
        <p className="mt-3 rounded-lg border border-clay/40 bg-clay/10 px-3 py-2 text-sm text-clay">
          {(link.error as Error).message}
        </p>
      )}
      {result && !link.isError && (
        <p
          className={`mt-3 rounded-lg px-3 py-2 text-sm ${
            result.includes("DEMO")
              ? "border border-clay/40 bg-clay/10 text-clay"
              : "text-acid"
          }`}
        >
          {result}
        </p>
      )}
    </div>
  );
}

export function ConnectionList() {
  const refresh = useRefreshAll();
  const [notes, setNotes] = useState<Record<string, string>>({});
  const { data = [] } = useQuery({
    queryKey: ["connections"],
    queryFn: () => apiFetch<Connection[]>("/connections"),
  });

  const sync = useMutation({
    mutationFn: (id: string) =>
      apiFetch<SyncResult>(`/connections/${id}/sync`, { method: "POST" }),
    onSuccess: (r, id) => {
      setNotes((n) => ({ ...n, [id]: summarize(r) }));
      refresh();
    },
    onError: (e, id) => setNotes((n) => ({ ...n, [id]: (e as Error).message })),
  });

  const forget = useMutation({
    mutationFn: (id: string) => apiFetch(`/connections/${id}`, { method: "DELETE" }),
    onSuccess: refresh,
  });

  if (data.length === 0) return null;

  return (
    <div className="card p-5">
      <h2 className="mb-4 text-sm font-medium">Connected</h2>
      <ul className="divide-y divide-line">
        {data.map((c) => (
          <li key={c.id} className="flex flex-wrap items-center gap-3 py-3 first:pt-0 last:pb-0">
            <span className="min-w-0 flex-1">
              <span className="block text-sm capitalize">
                {c.provider}
                {c.is_demo && (
                  <span className="ml-2 rounded-full border border-clay/50 px-2 py-0.5 text-[10px] tracking-widest text-clay uppercase">
                    demo
                  </span>
                )}
              </span>
              <span className="label">
                {c.is_demo ? "DEMO DATA · " : ""}
                {syncedAt(c.last_synced_at)}
                {c.status !== "active" && ` · ${c.status}`}
                {notes[c.id] && ` · ${notes[c.id]}`}
              </span>
            </span>
            <button
              onClick={() => sync.mutate(c.id)}
              disabled={sync.isPending}
              className="btn-ghost"
            >
              {sync.isPending && sync.variables === c.id ? "Syncing…" : "Sync now"}
            </button>
            <button
              onClick={() => forget.mutate(c.id)}
              className="text-[13px] text-muted transition-colors hover:text-clay"
            >
              Forget
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
