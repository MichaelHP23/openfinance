import { useState } from "react";
import { useForm } from "react-hook-form";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { API_BASE, apiFetch } from "./api/client";
import { useTransactions, type Txn } from "./data";
import { shortDate, usd } from "./money";
import { Empty } from "./ui/Shell";

export function TxnRows({ txns }: { txns: Txn[] }) {
  return (
    <table className="w-full">
      <tbody>
        {txns.map((t, i) => (
          <tr
            key={t.id}
            className="rise border-b border-line/60 transition-colors last:border-0 hover:bg-[rgba(237,234,228,0.02)]"
            style={{ "--d": `${Math.min(i, 12) * 30}ms` } as React.CSSProperties}
          >
            <td className="tnum w-24 py-3 text-[13px] text-muted">{shortDate(t.posted_at)}</td>
            <td className="py-3 text-sm">{t.merchant_raw}</td>
            <td
              className={`tnum py-3 text-right text-sm ${
                Number(t.amount) > 0 ? "text-acid" : "text-bone"
              }`}
            >
              {Number(t.amount) > 0 ? `+${usd(t.amount)}` : usd(t.amount)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function TransactionList() {
  const [search, setSearch] = useState("");
  const { data = [], isLoading } = useTransactions(search);

  return (
    <div>
      <input
        className="mb-3 w-full"
        placeholder="Search merchant…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
      {isLoading ? (
        <Empty>Loading…</Empty>
      ) : data.length === 0 ? (
        <Empty>{search ? `Nothing matching “${search}”.` : "No transactions yet."}</Empty>
      ) : (
        <TxnRows txns={data} />
      )}
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
    <form onSubmit={handleSubmit((f) => mut.mutate(f))} className="flex flex-wrap items-end gap-3">
      <label className="flex flex-col gap-1.5">
        <span className="label">Date</span>
        <input type="date" aria-label="Date" {...register("posted_at", { required: true })} />
      </label>
      <label className="flex flex-1 flex-col gap-1.5">
        <span className="label">Merchant</span>
        <input placeholder="Merchant" {...register("merchant_raw", { required: true })} />
      </label>
      <label className="flex flex-col gap-1.5">
        <span className="label">Amount</span>
        <input
          className="tnum w-32"
          aria-label="Amount"
          placeholder="-9.99"
          {...register("amount", { required: true })}
        />
      </label>
      <button disabled={!accountId} className="btn">
        Add transaction
      </button>
      {mut.isError && <span className="text-sm text-clay">{(mut.error as Error).message}</span>}
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
    setStatus(
      res.ok ? `Imported ${out.imported}, skipped ${out.skipped}` : (out.detail ?? "Import failed"),
    );
    qc.invalidateQueries({ queryKey: ["transactions"] });
    e.target.value = "";
  };

  return (
    <div className="flex flex-wrap items-center gap-3">
      <label className="flex flex-col gap-1.5">
        <span className="label">Import CSV</span>
        <input type="file" accept=".csv" aria-label="Import CSV" onChange={onFile} />
      </label>
      <span className="text-[13px] text-muted">
        {status || "Columns: date, amount, merchant. Re-importing the same file is deduped."}
      </span>
    </div>
  );
}
