import { useState } from "react";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { API_BASE, apiFetch } from "./api/client";

export type Txn = {
  id: string;
  posted_at: string;
  merchant_raw: string;
  amount: string;
  currency: string;
};

export function TransactionList() {
  const [search, setSearch] = useState("");
  const { data = [] } = useQuery({
    queryKey: ["transactions", search],
    queryFn: () =>
      apiFetch<Txn[]>(`/transactions${search ? `?search=${encodeURIComponent(search)}` : ""}`),
  });
  return (
    <div>
      <input
        className="mb-2 w-full rounded border p-2"
        placeholder="Search merchant…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
      <table className="w-full text-sm">
        <tbody>
          {data.map((t) => (
            <tr key={t.id} className="border-b">
              <td className="p-2">{t.posted_at.slice(0, 10)}</td>
              <td className="p-2">{t.merchant_raw}</td>
              <td className="p-2 text-right">
                {t.currency} {t.amount}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type Form = { posted_at: string; amount: string; merchant_raw: string };

export function NewTransactionForm({ accountId }: { accountId: string }) {
  const qc = useQueryClient();
  const { register, handleSubmit, reset } = useForm<Form>();
  const mut = useMutation({
    mutationFn: (f: Form) =>
      apiFetch("/transactions", {
        method: "POST",
        body: JSON.stringify({
          account_id: accountId,
          // <input type="date"> gives YYYY-MM-DD; the API wants a datetime.
          posted_at: `${f.posted_at}T00:00:00Z`,
          amount: f.amount,
          merchant_raw: f.merchant_raw,
        }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["transactions"] });
      reset();
    },
  });
  return (
    <form onSubmit={handleSubmit((f) => mut.mutate(f))} className="flex flex-wrap gap-2">
      <input
        className="rounded border p-2"
        type="date"
        aria-label="Date"
        {...register("posted_at", { required: true })}
      />
      <input
        className="rounded border p-2"
        placeholder="Merchant"
        {...register("merchant_raw", { required: true })}
      />
      <input
        className="w-28 rounded border p-2"
        aria-label="Amount"
        placeholder="-9.99"
        {...register("amount", { required: true })}
      />
      <button disabled={!accountId} className="rounded bg-black px-3 text-white">
        Add transaction
      </button>
      {mut.isError && <span className="text-sm text-red-600">{(mut.error as Error).message}</span>}
    </form>
  );
}

export function CsvUpload({ accountId }: { accountId: string }) {
  const qc = useQueryClient();
  const [status, setStatus] = useState("");

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !accountId) return;
    const body = new FormData();
    body.append("file", file);
    const res = await fetch(`${API_BASE}/accounts/${accountId}/import`, {
      method: "POST",
      credentials: "include",
      body,
    });
    const out = await res.json().catch(() => ({}));
    setStatus(res.ok ? `Imported ${out.imported}, skipped ${out.skipped}` : (out.detail ?? "Import failed"));
    qc.invalidateQueries({ queryKey: ["transactions"] });
    e.target.value = "";
  };

  return (
    <label className="flex items-center gap-2 text-sm">
      <span>Import CSV</span>
      <input type="file" accept=".csv" aria-label="Import CSV" onChange={onFile} />
      {status && <span className="text-gray-600">{status}</span>}
    </label>
  );
}
