import { useState } from "react";
import { useForm } from "react-hook-form";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./api/client";
import { ACCOUNT_TYPES, useAccounts } from "./data";
import { LIABILITY_TYPES, prettyType, usd } from "./money";
import { Empty } from "./ui/Shell";

const initials = (name: string) =>
  name
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0])
    .join("")
    .toUpperCase();

export function AccountList() {
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState<string | null>(null);
  const { data = [], isLoading } = useAccounts();
  const remove = useMutation({
    mutationFn: (id: string) => apiFetch(`/accounts/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["accounts"] });
      qc.invalidateQueries({ queryKey: ["transactions"] });
      qc.invalidateQueries({ queryKey: ["net-worth"] });
    },
  });
  if (isLoading) return <Empty>Loading accounts…</Empty>;
  if (data.length === 0) return <Empty>No accounts yet — add your first one above.</Empty>;

  return (
    <ul className="divide-y divide-line">
      {data.map((a, i) => (
        <li
          key={a.id}
          className="rise flex items-center gap-4 py-3.5 transition-colors first:pt-0 last:pb-0 hover:bg-[rgba(237,234,228,0.02)]"
          style={{ "--d": `${i * 40}ms` } as React.CSSProperties}
        >
          <span className="tnum flex size-9 shrink-0 items-center justify-center rounded-lg border border-line bg-ink text-[11px] text-muted">
            {initials(a.name)}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm">{a.name}</span>
            <span className="label">
              {prettyType(a.type)}
              {a.institution ? ` · ${a.institution}` : ""}
            </span>
          </span>
          <span
            className={`tnum text-sm ${LIABILITY_TYPES.has(a.type) ? "text-clay" : "text-bone"}`}
          >
            {LIABILITY_TYPES.has(a.type) ? `−${usd(Math.abs(Number(a.balance)))}` : usd(a.balance)}
          </span>
          <button
            onClick={() => setConfirming(confirming === a.id ? null : a.id)}
            aria-label={`Remove ${a.name}`}
            className="text-[13px] text-muted transition-colors hover:text-clay"
          >
            {confirming === a.id ? "Cancel" : "Remove"}
          </button>
          {confirming === a.id && (
            <button
              onClick={() => {
                remove.mutate(a.id);
                setConfirming(null);
              }}
              className="text-[13px] text-clay underline underline-offset-2"
            >
              Delete account and its transactions
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}

type Form = { name: string; type: string; balance: string; institution: string };

export function NewAccountForm() {
  const qc = useQueryClient();
  const { register, handleSubmit, reset } = useForm<Form>({
    defaultValues: { type: "checking", balance: "0" },
  });
  const mut = useMutation({
    mutationFn: (f: Form) =>
      apiFetch("/accounts", {
        method: "POST",
        body: JSON.stringify({ ...f, institution: f.institution || null }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["accounts"] });
      reset();
    },
  });

  return (
    <form onSubmit={handleSubmit((f) => mut.mutate(f))} className="flex flex-wrap items-end gap-3">
      <label className="flex flex-col gap-1.5">
        <span className="label">Name</span>
        <input placeholder="Main Checking" {...register("name", { required: true })} />
      </label>
      <label className="flex flex-col gap-1.5">
        <span className="label">Type</span>
        <select aria-label="Account type" {...register("type")}>
          {ACCOUNT_TYPES.map((t) => (
            <option key={t} value={t}>
              {prettyType(t)}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1.5">
        <span className="label">Institution</span>
        <input placeholder="Optional" {...register("institution")} />
      </label>
      <label className="flex flex-col gap-1.5">
        <span className="label">Balance</span>
        <input className="tnum w-32" placeholder="0.00" {...register("balance")} />
      </label>
      <button className="btn">Add</button>
      {mut.isError && <span className="text-sm text-clay">{(mut.error as Error).message}</span>}
    </form>
  );
}
